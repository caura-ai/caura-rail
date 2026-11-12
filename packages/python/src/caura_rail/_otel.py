"""Optional OpenTelemetry spans and W3C trace propagation.

Active only when ``opentelemetry-api`` is installed (``pip install
"caura-rail[otel]"``) and the application has configured an OpenTelemetry SDK.
Without the package every helper here does nothing; without an SDK the API's
own tracer records nothing and no ``traceparent`` header is sent.

Span and attribute names follow the OpenTelemetry GenAI memory conventions at
open-telemetry/semantic-conventions-genai commit ``SEMCONV_GENAI_COMMIT``, the
same revision the Caura server pins. Memory content is never recorded; the
recall query is recorded only when ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_CONTENT``
is ``SPAN_ONLY`` or ``SPAN_AND_EVENT``.
"""

import os
from collections.abc import Iterator, MutableMapping
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from .models import MemoryScope, StoreError

try:
    from opentelemetry import context as _context
    from opentelemetry import trace as _trace
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    _trace_context = TraceContextTextMapPropagator()
except ImportError:  # pragma: no cover - exercised by the wheel smoke test in CI
    _trace = None  # type: ignore[assignment]

SEMCONV_GENAI_COMMIT = "e6658f14c9d9ea0760825f029cb82e7673f48fab"
CAPTURE_CONTENT_ENV = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_CONTENT"

OP_SEARCH = "search_memory"
OP_CREATE = "create_memory"
TURN_SPAN = "caura.rail.turn"
REPLAY_SPAN = "caura.outbox.replay"


def _tracer() -> Any:
    assert _trace is not None
    from . import __version__

    return _trace.get_tracer(
        "caura_rail",
        __version__,
        attributes={"caura.semconv.genai.commit": SEMCONV_GENAI_COMMIT},
    )


def enabled() -> bool:
    return _trace is not None


def capture_query_text() -> bool:
    setting = os.environ.get(CAPTURE_CONTENT_ENV, "").strip().upper()
    return setting in {"SPAN_ONLY", "SPAN_AND_EVENT"}


def inject(headers: MutableMapping[str, str]) -> None:
    """Add ``traceparent`` (and ``tracestate``) for the current span, if any.

    The W3C trace-context propagator alone, not the global one: that also
    carries W3C ``baggage`` by default (and whatever ``OTEL_PROPAGATORS``
    names), and an application's baggage can hold user or session ids that
    have no business reaching the memory server.
    """
    if _trace is not None:
        _trace_context.inject(headers)


def error_type(exc: BaseException) -> str:
    if isinstance(exc, StoreError) and exc.status is not None:
        return str(exc.status)
    return type(exc).__qualname__


def utf8_len(texts: Any) -> int:
    return sum(len(text.encode("utf-8")) for text in texts if isinstance(text, str))


class Span:
    """A started span, or nothing at all when OpenTelemetry is not installed."""

    def __init__(self, span: Any = None) -> None:
        self._span = span

    def set(self, key: str, value: Any) -> None:
        if self._span is not None and value is not None:
            self._span.set_attribute(key, value)

    def fail(self, exc: BaseException) -> None:
        if self._span is not None:
            self._span.set_attribute("error.type", error_type(exc))
            self._span.set_status(_trace.Status(_trace.StatusCode.ERROR))


def _memory_attributes(operation: str, scope: MemoryScope) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": operation,
        "gen_ai.provider.name": "caura",
        "gen_ai.agent.id": scope.agent_id,
    }
    if scope.tenant_id:
        attributes["gen_ai.memory.store.id"] = scope.tenant_id
    return attributes


@contextmanager
def span(name: str, attributes: dict[str, Any], *, client: bool = False) -> Iterator[Span]:
    """Run the block inside a span; record the failure of anything it raises.

    Exception messages are not recorded: a store error can quote content.
    """
    if _trace is None:
        yield Span()
        return
    kind = _trace.SpanKind.CLIENT if client else _trace.SpanKind.INTERNAL
    with _tracer().start_as_current_span(
        name,
        kind=kind,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as current:
        handle = Span(current)
        try:
            yield handle
        except BaseException as exc:
            handle.fail(exc)
            raise


def memory_span(
    operation: str, scope: MemoryScope, extra: dict[str, Any] | None = None
) -> "AbstractContextManager[Span]":
    """A CLIENT span for one call to the memory store."""
    attributes = _memory_attributes(operation, scope)
    attributes.update({k: v for k, v in (extra or {}).items() if v is not None})
    return span(operation, attributes, client=True)


class TurnSpan:
    """The span around one turn, current from recall to commit so the store
    calls and whatever the agent itself traces nest inside it."""

    def __init__(self, scope: MemoryScope) -> None:
        self._span: Any = None
        self._token: Any = None
        if _trace is not None:
            self._span = _tracer().start_span(
                TURN_SPAN,
                kind=_trace.SpanKind.INTERNAL,
                attributes={"gen_ai.provider.name": "caura", "gen_ai.agent.id": scope.agent_id},
            )
            self._token = _context.attach(_trace.set_span_in_context(self._span))

    def end(self, *, degraded: bool, writes: int, exc: BaseException | None = None) -> None:
        if self._span is None:
            return
        handle = Span(self._span)
        handle.set("caura.rail.degraded", degraded)
        handle.set("caura.rail.writes", writes)
        if exc is not None:
            handle.fail(exc)
        try:
            _context.detach(self._token)
        finally:
            self._span.end()
            self._span = None
