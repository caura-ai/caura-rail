/**
 * Optional OpenTelemetry spans and W3C trace propagation.
 *
 * Active only when `@opentelemetry/api` can be imported (an optional peer
 * dependency) and the application has registered an OpenTelemetry SDK and a
 * context manager. Without the package nothing here does anything; without an
 * SDK the API's own tracer records nothing and no `traceparent` is sent.
 *
 * Span and attribute names follow the OpenTelemetry GenAI memory conventions at
 * open-telemetry/semantic-conventions-genai commit `SEMCONV_GENAI_COMMIT`, as
 * the Python package and the Caura server do. Memory content and error messages
 * are never recorded; the recall query is recorded only when
 * `OTEL_INSTRUMENTATION_GENAI_CAPTURE_CONTENT` is `SPAN_ONLY` or `SPAN_AND_EVENT`.
 *
 * Internal: not exported from the package root.
 */
import { type MemoryScope, StoreError } from "./models.js";
import { VERSION } from "./version.js";

export const SEMCONV_GENAI_COMMIT = "e6658f14c9d9ea0760825f029cb82e7673f48fab";
export const CAPTURE_CONTENT_ENV = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_CONTENT";
export const OP_SEARCH = "search_memory";
export const OP_CREATE = "create_memory";
export const TURN_SPAN = "caura.rail.turn";
export const REPLAY_SPAN = "caura.outbox.replay";
const TRACER = "@caura/rail";

// The few parts of @opentelemetry/api used here, declared structurally so the
// published types need no OpenTelemetry package.
type Attributes = Record<string, string | number | boolean>;
interface Span {
  setAttribute(key: string, value: string | number | boolean): unknown;
  setStatus(status: { code: number }): unknown;
  end(): void;
}
interface SpanContext { traceId: string; spanId: string; traceFlags: number; traceState?: { serialize(): string } }
interface Api {
  trace: {
    getTracer(name: string, version?: string): {
      startSpan(name: string, options: { kind: number; attributes?: Attributes }, context?: unknown): Span;
    };
    setSpan(context: unknown, span: Span): unknown;
    getSpanContext(context: unknown): SpanContext | undefined;
  };
  context: { active(): unknown; with<T>(context: unknown, fn: () => T): T };
  isSpanContextValid(spanContext: SpanContext): boolean;
  SpanKind: { INTERNAL: number; CLIENT: number };
  SpanStatusCode: { ERROR: number };
}

// A variable rather than a literal, with the bundler hints below: an
// application bundled without the package must still build, with tracing off.
const API_PACKAGE = "@opentelemetry/api";
let loading: Promise<Api | undefined> | undefined;

/** The OpenTelemetry API, or undefined when it cannot be imported. Loaded once. */
export function loadOtel(): Promise<Api | undefined> {
  loading ??= import(/* webpackIgnore: true */ /* @vite-ignore */ API_PACKAGE).then(
    (module: Api & { default?: Api }) => (module.trace ? module : module.default),
    () => undefined,
  );
  return loading;
}

/** Tests only: replace the loaded API, or simulate its absence with `null`. */
export function setOtelForTesting(api: unknown): void {
  loading = Promise.resolve((api ?? undefined) as Api | undefined);
}

export function captureQueryText(): boolean {
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
  const setting = (env?.[CAPTURE_CONTENT_ENV] ?? "").trim().toUpperCase();
  return setting === "SPAN_ONLY" || setting === "SPAN_AND_EVENT";
}

const encoder = new TextEncoder();

export function utf8Length(texts: Iterable<unknown>): number {
  let total = 0;
  for (const text of texts) if (typeof text === "string") total += encoder.encode(text).length;
  return total;
}

export function errorType(error: unknown): string {
  if (error instanceof StoreError && error.status !== undefined) return String(error.status);
  if (error instanceof Error) return error.name;
  return typeof error;
}

/** A started span, or nothing at all when tracing is off. */
export class SpanHandle {
  constructor(private readonly span?: Span, private readonly api?: Api) {}

  set(key: string, value: string | number | boolean | undefined): void {
    if (this.span && value !== undefined) this.span.setAttribute(key, value);
  }

  /** Mark the span failed. Messages are not recorded: a store error can quote content. */
  fail(error: unknown): void {
    if (!this.span || !this.api) return;
    this.span.setAttribute("error.type", errorType(error));
    this.span.setStatus({ code: this.api.SpanStatusCode.ERROR });
  }
}

/**
 * Run `fn` inside a span that is the active one for everything it awaits,
 * store requests and the agent's own spans included. A throw marks the span
 * failed and is rethrown; the span always ends.
 */
async function inSpan<T>(
  name: string, attributes: Attributes, client: boolean,
  fn: (span: SpanHandle) => Promise<T>,
): Promise<T> {
  const api = await loadOtel();
  if (!api) return fn(new SpanHandle());
  const span = api.trace.getTracer(TRACER, VERSION).startSpan(
    name, { kind: client ? api.SpanKind.CLIENT : api.SpanKind.INTERNAL, attributes },
  );
  const handle = new SpanHandle(span, api);
  try {
    return await api.context.with(api.trace.setSpan(api.context.active(), span), () => fn(handle));
  } catch (error) {
    handle.fail(error);
    throw error;
  } finally {
    span.end();
  }
}

function memoryAttributes(operation: string, scope: MemoryScope, extra: Attributes): Attributes {
  const attributes: Attributes = {
    "gen_ai.operation.name": operation,
    "gen_ai.provider.name": "caura",
    "gen_ai.agent.id": scope.agentId,
  };
  if (scope.tenantId) attributes["gen_ai.memory.store.id"] = scope.tenantId;
  return { ...attributes, ...extra };
}

/** A CLIENT span for one call to the memory store. */
export function memorySpan<T>(
  operation: string, scope: MemoryScope, extra: Attributes, fn: (span: SpanHandle) => Promise<T>,
): Promise<T> {
  return inSpan(operation, memoryAttributes(operation, scope, extra), true, fn);
}

export function internalSpan<T>(
  name: string, attributes: Attributes, fn: (span: SpanHandle) => Promise<T>,
): Promise<T> {
  return inSpan(name, attributes, false, fn);
}

/**
 * The span around one turn, active from recall to commit. `report` is read when
 * the turn ends, however it ends, so the span carries what the turn did.
 */
export function turnSpan<T>(
  scope: MemoryScope, report: { readonly degraded: boolean; readonly writes: readonly unknown[] },
  fn: () => Promise<T>,
): Promise<T> {
  const attributes = { "gen_ai.provider.name": "caura", "gen_ai.agent.id": scope.agentId };
  return internalSpan(TURN_SPAN, attributes, async span => {
    try {
      return await fn();
    } finally {
      span.set("caura.rail.degraded", report.degraded);
      span.set("caura.rail.writes", report.writes.length);
    }
  });
}

/**
 * Add `traceparent` (and `tracestate`) for the active span, if any. Written
 * from the span context per W3C Trace Context rather than through the global
 * propagator: that one also carries W3C `baggage` by default, and whatever an
 * application registers, and baggage can hold user or session ids that have no
 * business reaching the memory server.
 */
export async function injectTraceContext(headers: Record<string, string>): Promise<void> {
  const api = await loadOtel();
  if (!api) return;
  const spanContext = api.trace.getSpanContext(api.context.active());
  if (!spanContext || !api.isSpanContextValid(spanContext)) return;
  const flags = (spanContext.traceFlags & 0xff).toString(16).padStart(2, "0");
  headers.traceparent = `00-${spanContext.traceId}-${spanContext.spanId}-${flags}`;
  const state = spanContext.traceState?.serialize();
  if (state) headers.tracestate = state;
}

export function searchAttributes(kind: "rules" | "facts", query?: string): Attributes {
  const attributes: Attributes = { "caura.recall.kind": kind };
  if (query !== undefined && captureQueryText()) attributes["gen_ai.memory.query.text"] = query;
  return attributes;
}

export function writeAttributes(fact: string, scope: MemoryScope, attempt?: number): Attributes {
  const attributes: Attributes = {
    "gen_ai.memory.record.count": 1,
    "caura.scope": scope.visibility,
    "caura.payload.bytes": utf8Length([fact]),
  };
  if (attempt !== undefined) attributes["caura.outbox.attempt"] = attempt;
  return attributes;
}

export function recordFound(span: SpanHandle, items: readonly { content: string }[]): void {
  span.set("gen_ai.memory.record.count", items.length);
  span.set("caura.payload.bytes", utf8Length(items.map(item => item.content)));
}

export function recordWrite(span: SpanHandle, result: { status: string; id?: string }): void {
  span.set("gen_ai.memory.record.id", result.id);
  span.set("caura.write.status", result.status);
}
