"""OpenTelemetry spans and trace propagation (caura_rail._otel)."""

import asyncio

import httpx
import pytest
from opentelemetry import baggage, trace
from opentelemetry import context as otel_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from caura_rail import (
    AsyncRail,
    Fact,
    KeystoneRule,
    MemoryScope,
    Rail,
    RestMemoryStore,
    StoreError,
    Visibility,
    WriteResult,
    _otel,
)

SCOPE = MemoryScope(agent_id="agent", tenant_id="t-1", fleet_id="f", visibility=Visibility.TEAM)
FACT = "Remember: the customer's card ends in 4242"
STORED = "the customer's card ends in 4242"
RECALLED = "the customer prefers email"


@pytest.fixture
def spans(monkeypatch):
    monkeypatch.delenv(_otel.CAPTURE_CONTENT_ENV, raising=False)
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(_otel, "_tracer", lambda: provider.get_tracer("test"))
    return exporter


class Store:
    def __init__(self, fail_write=None):
        self.fail_write = fail_write

    def keystones(self, scope):
        return [KeystoneRule("k1", "Rule", "Be polite", 5)]

    def recall(self, query, scope, top_k):
        return [Fact("m0", RECALLED)]

    def write(self, fact, scope):
        if self.fail_write:
            raise self.fail_write
        return WriteResult("written", id="m1")


class AsyncStore(Store):
    async def keystones(self, scope):
        return super().keystones(scope)

    async def recall(self, query, scope, top_k):
        return super().recall(query, scope, top_k)

    async def write(self, fact, scope):
        return super().write(fact, scope)


def _by_name(exporter):
    found = {}
    for s in exporter.get_finished_spans():
        found.setdefault(s.name, []).append(s)
    return found


def _values(span):
    return [str(v) for v in span.attributes.values()]


def _assert_one_turn_trace(exporter):
    named = _by_name(exporter)
    (turn,) = named["caura.rail.turn"]
    rules, facts = named["search_memory"]
    (write,) = named["create_memory"]
    for child in (rules, facts, write):
        assert child.context.trace_id == turn.context.trace_id
        assert child.parent.span_id == turn.context.span_id
        assert child.kind == SpanKind.CLIENT
    assert turn.kind == SpanKind.INTERNAL
    assert turn.attributes["gen_ai.agent.id"] == "agent"
    assert turn.attributes["caura.rail.writes"] == 1
    assert turn.attributes["caura.rail.degraded"] is False
    assert rules.attributes["caura.recall.kind"] == "rules"
    assert facts.attributes["caura.recall.kind"] == "facts"
    assert facts.attributes["gen_ai.memory.record.count"] == 1
    assert facts.attributes["caura.payload.bytes"] == len(RECALLED.encode())
    assert facts.attributes["gen_ai.memory.store.id"] == "t-1"
    assert write.attributes["gen_ai.operation.name"] == "create_memory"
    assert write.attributes["gen_ai.provider.name"] == "caura"
    assert write.attributes["gen_ai.memory.record.id"] == "m1"
    assert write.attributes["caura.write.status"] == "written"
    assert write.attributes["caura.scope"] == "scope_team"
    assert write.attributes["caura.payload.bytes"] == len(STORED.encode())
    for s in exporter.get_finished_spans():
        assert not any(text in v for v in _values(s) for text in (FACT, STORED, RECALLED))


def test_a_turn_is_one_trace(spans):
    rail = Rail(Store(), SCOPE)
    with rail.turn(FACT) as turn:
        turn.reply = "noted"
    _assert_one_turn_trace(spans)


async def test_an_async_turn_is_one_trace(spans):
    rail = AsyncRail(AsyncStore(), SCOPE)
    async with rail.turn(FACT) as turn:
        turn.reply = "noted"
    _assert_one_turn_trace(spans)


def test_the_agents_own_spans_nest_in_the_turn(spans):
    rail = Rail(Store(), SCOPE)
    tracer = _otel._tracer()
    with rail.turn("hello") as turn:
        with tracer.start_as_current_span("chat"):
            turn.reply = "hi"
    named = _by_name(spans)
    assert named["chat"][0].parent.span_id == named["caura.rail.turn"][0].context.span_id


@pytest.mark.parametrize(("setting", "captured"), [("SPAN_ONLY", True), ("event_only", False)])
def test_query_text_needs_the_span_opt_in(spans, monkeypatch, setting, captured):
    monkeypatch.setenv(_otel.CAPTURE_CONTENT_ENV, setting)
    Rail(Store(), SCOPE).recall("card on file")
    rules, facts = _by_name(spans)["search_memory"]
    assert ("gen_ai.memory.query.text" in facts.attributes) is captured
    assert "gen_ai.memory.query.text" not in rules.attributes


def test_query_text_is_off_by_default(spans):
    Rail(Store(), SCOPE).recall("card on file")
    assert all("card on file" not in _values(s) for s in spans.get_finished_spans())


def test_a_deferred_write_reports_its_failure(spans):
    rail = Rail(Store(fail_write=StoreError("busy", status=503, retryable=True)), SCOPE)
    with rail.turn(FACT) as turn:
        turn.reply = "noted"
    named = _by_name(spans)
    (write,) = named["create_memory"]
    assert write.attributes["error.type"] == "503"
    assert write.attributes["caura.write.status"] == "deferred"
    assert write.status.status_code == StatusCode.ERROR
    assert write.events == ()
    assert named["caura.rail.turn"][0].attributes["caura.rail.degraded"] is True


def test_a_failed_agent_fails_the_turn_span(spans):
    rail = Rail(Store(), SCOPE)
    with pytest.raises(RuntimeError):
        with rail.turn(FACT):
            raise RuntimeError("agent failed")
    (turn,) = _by_name(spans)["caura.rail.turn"]
    assert turn.attributes["error.type"] == "RuntimeError"
    assert turn.status.status_code == StatusCode.ERROR
    assert "create_memory" not in _by_name(spans)


class RulesDown(Store):
    def keystones(self, scope):
        raise StoreError(f"rules unavailable while reading {STORED}", status=502)


def test_a_store_error_that_ends_the_turn_is_recorded_without_its_message(spans):
    rail = Rail(RulesDown(), SCOPE, require_keystones=True)
    with pytest.raises(StoreError):
        with rail.turn(FACT):
            pass
    named = _by_name(spans)
    (rules,) = named["search_memory"]
    (turn,) = named["caura.rail.turn"]
    for span in (rules, turn):
        assert span.attributes["error.type"] == "502"
        assert span.status.status_code == StatusCode.ERROR
        assert span.events == ()
        assert not any(STORED in v for v in _values(span))
    assert turn.attributes["caura.rail.degraded"] is True


def test_outbox_replay_is_one_span_with_a_write_per_item(spans):
    store = Store(fail_write=StoreError("down", retryable=True))
    rail = Rail(store, SCOPE)
    with rail.turn(FACT) as turn:
        turn.reply = "noted"
    spans.clear()

    store.fail_write = None
    assert [r.status for r in rail.flush_outbox()] == ["written"]

    named = _by_name(spans)
    (replay,) = named["caura.outbox.replay"]
    (write,) = named["create_memory"]
    assert write.parent.span_id == replay.context.span_id
    assert write.attributes["caura.outbox.attempt"] == 1
    assert replay.attributes["caura.outbox.batch_size"] == 1
    assert replay.attributes["caura.outbox.deferred"] == 0
    assert replay.attributes["caura.outbox.dropped"] == 0


async def test_async_outbox_replay_counts_what_stays_behind(spans):
    store = AsyncStore(fail_write=StoreError("down", retryable=True))
    rail = AsyncRail(store, SCOPE)
    async with rail.turn(FACT) as turn:
        turn.reply = "noted"
    spans.clear()

    await rail.flush_outbox(max_attempts=3)

    named = _by_name(spans)
    (replay,) = named["caura.outbox.replay"]
    (write,) = named["create_memory"]
    assert replay.attributes["caura.outbox.deferred"] == 1
    assert write.parent.span_id == replay.context.span_id
    assert write.attributes["caura.outbox.attempt"] == 1
    assert write.attributes["caura.write.status"] == "deferred"


# ── The REST store carries the trace to the server ──


def _rest_store(seen):
    def handler(request):
        seen.append(request)
        if request.url.path == "/api/v1/keystones":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/v1/search":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(201, json={"id": "m1"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RestMemoryStore("http://caura.test", "key", tenant_id="t-1", client=client)


def test_each_request_carries_its_spans_traceparent(spans):
    seen = []
    rail = Rail(_rest_store(seen), SCOPE)
    with rail.turn(FACT) as turn:
        turn.reply = "noted"

    by_path = {r.url.path: r.headers.get("traceparent") for r in seen}
    named = _by_name(spans)
    trace_id = format(named["caura.rail.turn"][0].context.trace_id, "032x")
    rules, facts = named["search_memory"]
    expected = {
        "/api/v1/keystones": rules,
        "/api/v1/search": facts,
        "/api/v1/memories": named["create_memory"][0],
    }
    for path, span in expected.items():
        version, sent_trace, parent, _flags = by_path[path].split("-")
        assert (sent_trace, parent) == (trace_id, format(span.context.span_id, "016x"))


def test_application_baggage_never_reaches_the_server(spans):
    seen = []
    rail = Rail(_rest_store(seen), SCOPE)
    token = otel_context.attach(baggage.set_baggage("user.id", "alice@example.com"))
    try:
        with rail.turn(FACT) as turn:
            turn.reply = "noted"
    finally:
        otel_context.detach(token)

    assert seen and all("traceparent" in r.headers for r in seen)
    assert all("baggage" not in r.headers for r in seen)


class Broken(Store):
    def recall(self, query, scope, top_k):
        raise RuntimeError("store bug")


class AsyncBroken(AsyncStore):
    async def recall(self, query, scope, top_k):
        raise asyncio.CancelledError()


def _assert_turn_closed(exporter, error_type):
    (turn,) = _by_name(exporter)["caura.rail.turn"]
    assert turn.attributes["error.type"] == error_type
    assert turn.status.status_code == StatusCode.ERROR
    assert not trace.get_current_span().get_span_context().is_valid


def test_an_unexpected_recall_error_still_closes_the_turn(spans):
    with pytest.raises(RuntimeError):
        with Rail(Broken(), SCOPE).turn(FACT):
            pass
    _assert_turn_closed(spans, "RuntimeError")


async def test_a_cancelled_async_recall_still_closes_the_turn(spans):
    with pytest.raises(asyncio.CancelledError):
        async with AsyncRail(AsyncBroken(), SCOPE).turn(FACT):
            pass
    _assert_turn_closed(spans, "CancelledError")


def test_without_opentelemetry_nothing_is_traced_or_sent(spans, monkeypatch):
    monkeypatch.setattr(_otel, "_trace", None)
    seen = []
    rail = Rail(_rest_store(seen), SCOPE)
    with rail.turn(FACT) as turn:
        turn.reply = "noted"

    assert [w.status for w in turn.writes] == ["written"]
    assert all("traceparent" not in r.headers for r in seen)
    assert spans.get_finished_spans() == ()
