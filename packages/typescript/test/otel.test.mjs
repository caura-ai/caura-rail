import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";
import * as api from "@opentelemetry/api";
import { AsyncLocalStorageContextManager } from "@opentelemetry/context-async-hooks";
import { CompositePropagator, W3CBaggagePropagator, W3CTraceContextPropagator } from "@opentelemetry/core";
import { BasicTracerProvider, InMemorySpanExporter, SimpleSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { MemoryScope, Rail, RestMemoryStore, StoreError } from "../dist/index.js";
import { CAPTURE_CONTENT_ENV, setOtelForTesting } from "../dist/otel.js";

// What an application's SDK setup does (NodeSDK registers the same three).
// The propagator includes baggage on purpose: Rail must not use it.
const exporter = new InMemorySpanExporter();
api.trace.setGlobalTracerProvider(new BasicTracerProvider({ spanProcessors: [new SimpleSpanProcessor(exporter)] }));
api.context.setGlobalContextManager(new AsyncLocalStorageContextManager().enable());
api.propagation.setGlobalPropagator(new CompositePropagator({
  propagators: [new W3CTraceContextPropagator(), new W3CBaggagePropagator()],
}));

const scope = new MemoryScope({ agentId: "agent", tenantId: "t-1", fleetId: "f", visibility: "scope_team" });
// Multi-byte on purpose: caura.payload.bytes counts UTF-8 bytes, not characters.
const FACT = "Remember: the customer’s card ends in 4242";
const STORED = "the customer’s card ends in 4242";
const RECALLED = "the customer prefers email";
const bytes = text => new TextEncoder().encode(text).length;

beforeEach(() => {
  exporter.reset();
  delete process.env[CAPTURE_CONTENT_ENV];
  setOtelForTesting(api);
});

class Store {
  constructor({ failWrite, failRecall, failRules } = {}) {
    Object.assign(this, { failWrite, failRecall, failRules });
  }
  async keystones() {
    if (this.failRules) throw this.failRules;
    return [{ docId: "k1", title: "Rule", content: "Be polite", weight: 5 }];
  }
  async recall() {
    if (this.failRecall) throw this.failRecall;
    return [{ id: "m0", content: RECALLED }];
  }
  async write() {
    if (this.failWrite) throw this.failWrite;
    return { status: "written", id: "m1" };
  }
}

const spans = () => exporter.getFinishedSpans();
const named = name => spans().filter(s => s.name === name);
const parentId = span => span.parentSpanContext?.spanId;
const values = span => Object.values(span.attributes).map(String);
const noContent = (...texts) => {
  for (const span of spans()) {
    for (const value of values(span)) for (const text of texts) assert.ok(!value.includes(text), span.name);
  }
};

test("a turn is one trace", async () => {
  const turn = await new Rail({ store: new Store(), scope }).turn(FACT, () => "noted");
  assert.equal(turn.writes[0].status, "written");

  const [root] = named("caura.rail.turn");
  const [rules, facts] = named("search_memory");
  const [write] = named("create_memory");
  for (const child of [rules, facts, write]) {
    assert.equal(child.spanContext().traceId, root.spanContext().traceId);
    assert.equal(parentId(child), root.spanContext().spanId);
    assert.equal(child.kind, api.SpanKind.CLIENT);
  }
  assert.equal(root.kind, api.SpanKind.INTERNAL);
  assert.equal(parentId(root), undefined);
  assert.deepEqual(root.attributes, {
    "gen_ai.provider.name": "caura", "gen_ai.agent.id": "agent",
    "caura.rail.degraded": false, "caura.rail.writes": 1,
  });
  assert.equal(rules.attributes["caura.recall.kind"], "rules");
  assert.equal(facts.attributes["caura.recall.kind"], "facts");
  assert.equal(facts.attributes["gen_ai.memory.record.count"], 1);
  assert.equal(facts.attributes["caura.payload.bytes"], bytes(RECALLED));
  assert.equal(facts.attributes["gen_ai.memory.store.id"], "t-1");
  assert.deepEqual(write.attributes, {
    "gen_ai.operation.name": "create_memory", "gen_ai.provider.name": "caura",
    "gen_ai.agent.id": "agent", "gen_ai.memory.store.id": "t-1",
    "gen_ai.memory.record.count": 1, "caura.scope": "scope_team",
    "caura.payload.bytes": bytes(STORED),
    "gen_ai.memory.record.id": "m1", "caura.write.status": "written",
  });
  noContent(FACT, STORED, RECALLED);
});

test("the agent's own spans nest in the turn", async () => {
  const tracer = api.trace.getTracer("app");
  await new Rail({ store: new Store(), scope }).turn("hello", async () => {
    await tracer.startActiveSpan("chat", async span => { span.end(); });
    return "hi";
  });
  assert.equal(parentId(named("chat")[0]), named("caura.rail.turn")[0].spanContext().spanId);
});

for (const [setting, captured] of [["SPAN_ONLY", true], ["span_and_event", true], ["EVENT_ONLY", false]]) {
  test(`query text needs the span opt-in (${setting})`, async () => {
    process.env[CAPTURE_CONTENT_ENV] = setting;
    await new Rail({ store: new Store(), scope }).recall("card on file");
    const [rules, facts] = named("search_memory");
    assert.equal("gen_ai.memory.query.text" in facts.attributes, captured);
    if (captured) assert.equal(facts.attributes["gen_ai.memory.query.text"], "card on file");
    assert.ok(!("gen_ai.memory.query.text" in rules.attributes));
  });
}

test("query text is off by default", async () => {
  await new Rail({ store: new Store(), scope }).recall("card on file");
  noContent("card on file");
});

test("a deferred write reports its failure without its message", async () => {
  const store = new Store({ failWrite: new StoreError(`busy writing ${STORED}`, 503, true) });
  await new Rail({ store, scope }).turn(FACT, () => "noted");
  const [write] = named("create_memory");
  assert.equal(write.attributes["error.type"], "503");
  assert.equal(write.attributes["caura.write.status"], "deferred");
  assert.equal(write.status.code, api.SpanStatusCode.ERROR);
  assert.equal(write.status.message, undefined);
  assert.deepEqual(write.events, []);
  assert.equal(named("caura.rail.turn")[0].attributes["caura.rail.degraded"], true);
  noContent(STORED);
});

test("a failed agent fails the turn span", async () => {
  await assert.rejects(new Rail({ store: new Store(), scope }).turn(FACT, () => {
    throw new RangeError("agent failed");
  }));
  const [root] = named("caura.rail.turn");
  assert.equal(root.attributes["error.type"], "RangeError");
  assert.equal(root.status.code, api.SpanStatusCode.ERROR);
  assert.equal(named("create_memory").length, 0);
});

test("a store error that ends the turn is recorded without its message", async () => {
  const failRules = new StoreError(`rules unavailable while reading ${STORED}`, 502);
  const rail = new Rail({ store: new Store({ failRules }), scope, requireKeystones: true });
  await assert.rejects(rail.turn(FACT, () => "unused"));
  const [rules] = named("search_memory");
  const [root] = named("caura.rail.turn");
  for (const span of [rules, root]) {
    assert.equal(span.attributes["error.type"], "502");
    assert.equal(span.status.code, api.SpanStatusCode.ERROR);
    assert.deepEqual(span.events, []);
  }
  assert.equal(root.attributes["caura.rail.degraded"], true);
  noContent(STORED);
});

test("an unexpected recall error still closes the turn", async () => {
  const rail = new Rail({ store: new Store({ failRecall: new TypeError("store bug") }), scope });
  await assert.rejects(rail.turn(FACT, () => "unused"), TypeError);
  const [root] = named("caura.rail.turn");
  assert.equal(root.attributes["error.type"], "TypeError");
  assert.equal(api.trace.getActiveSpan(), undefined);
});

test("outbox replay is one span with a write per item", async () => {
  const store = new Store({ failWrite: new StoreError("down", undefined, true) });
  const rail = new Rail({ store, scope });
  await rail.turn(FACT, () => "noted");
  exporter.reset();

  store.failWrite = undefined;
  assert.deepEqual((await rail.flushOutbox()).map(r => r.status), ["written"]);
  const [replay] = named("caura.outbox.replay");
  const [write] = named("create_memory");
  assert.equal(parentId(write), replay.spanContext().spanId);
  assert.equal(write.attributes["caura.outbox.attempt"], 1);
  assert.deepEqual(replay.attributes, {
    "caura.outbox.batch_size": 1, "caura.outbox.deferred": 0, "caura.outbox.dropped": 0,
  });
});

test("outbox replay counts what stays behind", async () => {
  const rail = new Rail({ store: new Store({ failWrite: new StoreError("down", undefined, true) }), scope });
  await rail.turn(FACT, () => "noted");
  exporter.reset();

  await rail.flushOutbox(3);
  const [replay] = named("caura.outbox.replay");
  const [write] = named("create_memory");
  assert.equal(replay.attributes["caura.outbox.deferred"], 1);
  assert.equal(write.attributes["caura.write.status"], "deferred");
  assert.equal(write.attributes["error.type"], "StoreError");
});

// ── The REST store carries the trace to the server ──

function restStore(seen) {
  const fetch = async (url, init) => {
    const path = new URL(url).pathname;
    seen.push({ path, headers: init.headers });
    const body = path === "/api/v1/keystones" ? [] : path === "/api/v1/search" ? { items: [] } : { id: "m1" };
    return new Response(JSON.stringify(body), { status: path === "/api/v1/memories" ? 201 : 200 });
  };
  return new RestMemoryStore({ fetch, apiKey: "key", tenantId: "t-1" });
}

test("each request carries its span's traceparent", async () => {
  const seen = [];
  await new Rail({ store: restStore(seen), scope }).turn(FACT, () => "noted");
  const traceId = named("caura.rail.turn")[0].spanContext().traceId;
  const [rules, facts] = named("search_memory");
  const expected = { "/api/v1/keystones": rules, "/api/v1/search": facts, "/api/v1/memories": named("create_memory")[0] };
  assert.equal(seen.length, 3);
  for (const { path, headers } of seen) {
    const [version, sentTrace, parent] = headers.traceparent.split("-");
    assert.deepEqual([version, sentTrace, parent], ["00", traceId, expected[path].spanContext().spanId]);
  }
});

test("an upstream tracestate travels with the traceparent", async () => {
  const seen = [];
  const upstream = api.trace.setSpanContext(api.context.active(), {
    traceId: "4bf92f3577b34da6a3ce929d0e0e4736", spanId: "00f067aa0ba902b7",
    traceFlags: api.TraceFlags.SAMPLED, isRemote: true,
    traceState: api.createTraceState("vendor=opaque"),
  });
  await api.context.with(upstream, () =>
    new Rail({ store: restStore(seen), scope }).turn(FACT, () => "noted"));
  assert.ok(seen.length > 0);
  for (const { headers } of seen) {
    assert.equal(headers.traceparent.split("-")[1], "4bf92f3577b34da6a3ce929d0e0e4736");
    assert.equal(headers.tracestate, "vendor=opaque");
  }
});

test("application baggage never reaches the server", async () => {
  const seen = [];
  const withBaggage = api.propagation.setBaggage(
    api.context.active(), api.propagation.createBaggage({ "user.id": { value: "alice@example.com" } }),
  );
  await api.context.with(withBaggage, () =>
    new Rail({ store: restStore(seen), scope }).turn(FACT, () => "noted"));
  assert.ok(seen.length > 0 && seen.every(r => "traceparent" in r.headers));
  assert.ok(seen.every(r => !("baggage" in r.headers)));
});

test("without OpenTelemetry nothing is traced or sent", async () => {
  setOtelForTesting(null);
  const seen = [];
  const turn = await new Rail({ store: restStore(seen), scope }).turn(FACT, () => "noted");
  assert.deepEqual(turn.writes.map(w => w.status), ["written"]);
  assert.ok(seen.every(r => !("traceparent" in r.headers)));
  assert.deepEqual(spans(), []);
});
