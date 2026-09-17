import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  MemoryScope, Outbox, Rail, RestMemoryStore, StoreError, USER_AGENT, VERSION,
} from "../dist/index.js";

const contract = JSON.parse(await readFile(new URL("../../../contracts/caura.json", import.meta.url)));
const scope = new MemoryScope({ agentId: "support-1", fleetId: "support", visibility: "scope_team" });
const json = (data, status = 200, headers = {}) => new Response(JSON.stringify(data), { status, headers });

test("shared contract: discovery, scoped requests, nested rules, write and duplicate", async () => {
  const paths = [];
  let written = false;
  const fetch = async (url, init) => {
    const parsed = new URL(url);
    paths.push(parsed.pathname);
    assert.equal(init.headers["X-API-Key"], "test-key");
    assert.equal(init.headers["User-Agent"], USER_AGENT);
    if (parsed.pathname === "/api/v1/whoami") return json(contract.identity);
    assert.equal(init.headers["X-Tenant-ID"], contract.tenant);
    if (parsed.pathname === "/api/v1/keystones") {
      assert.deepEqual(Object.fromEntries(parsed.searchParams), {
        tenant_id: contract.tenant, agent_id: "support-1", fleet_id: "support",
      });
      return json(contract.keystones_response);
    }
    if (parsed.pathname === "/api/v1/search") {
      assert.deepEqual(JSON.parse(init.body), contract.search_request);
      return json(contract.search_response);
    }
    assert.equal(parsed.pathname, "/api/v1/memories");
    assert.deepEqual(JSON.parse(init.body), contract.write_request);
    if (written) return json(contract.duplicate_response, 409);
    written = true;
    return json(contract.write_response, 201);
  };
  const store = new RestMemoryStore({ fetch, apiKey: "test-key" });
  const rail = new Rail({ store, scope, extractor: () => [contract.fact] });
  const turn = await rail.turn(contract.query, (_, ctx) => {
    assert.equal(ctx.text, contract.context_text);
    return "Acknowledged";
  });
  assert.equal(turn.degraded, false);
  assert.equal(turn.writes[0].status, "written");
  assert.equal((await store.write(contract.fact, scope)).status, "deduplicated");
  assert.equal(paths.filter(p => p === "/api/v1/whoami").length, 1);
});

test("VERSION agrees with package.json", async () => {
  const pkg = JSON.parse(await readFile(new URL("../package.json", import.meta.url)));
  assert.equal(VERSION, pkg.version);
});

test("User-Agent names the SDK and nothing else", () => {
  assert.equal(USER_AGENT, `caura-rail-node/${VERSION} (node/${process.versions.node.split(".")[0]})`);
  assert.match(USER_AGENT, /^caura-rail-node\/\d+\.\d+\.\d+ \(node\/\d+\)$/);
});

for (const status of [401, 403, 404, 422, 429, 503]) {
  test("HTTP " + status + " classification without response-body leakage", async () => {
    const store = new RestMemoryStore({
      tenantId: "tenant", fetch: async () => json({ detail: "private data" }, status),
    });
    await assert.rejects(store.recall("query", scope), error =>
      error instanceof StoreError && error.status === status &&
      error.retryable === [429, 503].includes(status) && !error.message.includes("private data"));
  });
}

for (const payload of [{}, { items: null }, { items: [null] }, { items: [{}] }]) {
  test("malformed search response " + JSON.stringify(payload), async () => {
    const store = new RestMemoryStore({ tenantId: "tenant", fetch: async () => json(payload) });
    assert.equal((await new Rail({ store, scope }).recall("query")).degraded, true);
  });
}

test("missing discovery identity does not become a default tenant", async () => {
  const paths = [];
  const store = new RestMemoryStore({ fetch: async url => {
    paths.push(new URL(url).pathname);
    return json({ tenant_id: null });
  } });
  await assert.rejects(store.write("fact", scope), StoreError);
  assert.deepEqual(paths, ["/api/v1/whoami"]);
});

test("explicit tenant and mismatch", async () => {
  const store = new RestMemoryStore({ tenantId: "explicit", fetch: async (url, init) => {
    assert.equal(new URL(url).pathname, "/api/v1/search");
    assert.equal(JSON.parse(init.body).tenant_id, "explicit");
    return json({ items: [] });
  } });
  assert.deepEqual(await store.recall("query", scope), []);
  await assert.rejects(store.recall("query", new MemoryScope({
    agentId: "agent", tenantId: "other",
  })), /does not match/);
});

test("only identified duplicates count as success; vanished winner can retry", async () => {
  const race = structuredClone(contract.duplicate_response);
  race.error.details = { reason: "winner_no_longer_live" };
  for (const [body, retryable] of [[{ detail: "Conflict" }, false], [race, true]]) {
    const store = new RestMemoryStore({ tenantId: "tenant", fetch: async () => json(body, 409) });
    await assert.rejects(store.write("fact", scope),
      error => error instanceof StoreError && error.retryable === retryable);
  }
});

test("keystone envelope and truncation flag", async () => {
  for (const truncated of [false, true]) {
    const store = new RestMemoryStore({ tenantId: "tenant", fetch: async () =>
      json({ items: contract.keystones_response }, 200, { "X-Truncated": String(truncated) }) });
    if (truncated) await assert.rejects(store.keystones(scope), /truncated/);
    else assert.equal((await store.keystones(scope))[0].weight, 100);
  }
});

function memoryStore() {
  return {
    facts: [], fail: false, retryable: true, hook: undefined,
    async keystones() {
      if (this.fail) throw new StoreError("outage", undefined, true);
      return [];
    },
    async recall() { return this.facts.map((content, i) => ({ id: String(i), content })); },
    async write(fact) {
      if (this.hook) await this.hook();
      if (this.fail) throw new StoreError("write failed", undefined, this.retryable);
      this.facts.push(fact);
      return { status: "written", id: String(this.facts.length) };
    },
  };
}

test("round trip and failed agent skips persistence", async () => {
  const store = memoryStore(), rail = new Rail({ store, scope });
  assert.equal(await rail.run("Remember: durable fact", () => "OK"), "OK");
  assert.equal((await rail.recall("query")).facts[0].content, "durable fact");
  await assert.rejects(rail.turn("Remember: partial fact", () => { throw new Error("agent failed"); }));
  assert.deepEqual(store.facts, ["durable fact"]);
});

test("outage recovery and permanent rejection", async () => {
  const store = memoryStore(), rail = new Rail({ store, scope });
  store.fail = true;
  const turn = await rail.turn("Remember: fact", () => "answer");
  assert.equal(turn.reply, "answer");
  assert.equal(turn.writes[0].status, "deferred");
  assert.equal(rail.telemetry.degradedTurns, 1);
  store.fail = false;
  assert.equal((await rail.flushOutbox())[0].status, "written");
  assert.equal(rail.outbox.size, 0);
  store.fail = true;
  store.retryable = false;
  await rail.run("Remember: rejected", () => "answer");
  assert.equal(rail.outbox.size, 0);
  assert.equal(rail.telemetry.writesRejected, 1);
});

test("bad extractor output preserves the agent answer", async () => {
  for (const value of [null, "not a list", [null], ["x".repeat(4001)]]) {
    const store = memoryStore(), rail = new Rail({ store, scope, extractor: () => value });
    assert.equal(await rail.run("message", () => "answer"), "answer");
    assert.equal(rail.telemetry.extractionFailures, 1);
    assert.deepEqual(store.facts, []);
  }
});

test("required keystones stop agent execution", async () => {
  const store = memoryStore();
  store.fail = true;
  const rail = new Rail({ store, scope, requireKeystones: true });
  let called = false;
  await assert.rejects(rail.run("query", () => { called = true; return "answer"; }), StoreError);
  assert.equal(called, false);
  assert.equal(rail.telemetry.degradedTurns, 1);
});

test("enqueue during replay counts capacity eviction; retries are bounded", async () => {
  const store = memoryStore(), rail = new Rail({ store, scope, outbox: new Outbox(1) });
  store.fail = true;
  await rail.run("Remember: old", () => "OK");
  store.hook = async () => {
    store.hook = undefined;
    await rail.run("Remember: new", () => "OK");
  };
  assert.equal((await rail.flushOutbox())[0].status, "deferred");
  assert.equal(rail.outbox.totalDropped, 1);
  assert.equal(rail.outbox.size, 1);
  assert.equal((await rail.flushOutbox(2))[0].status, "dropped");
  assert.equal(rail.outbox.totalDropped, 2);
});

test("context budget keeps rules ahead of facts", async () => {
  const store = memoryStore();
  store.keystones = async () => [{ docId: "rule", title: "Policy", content: "Preserve me", weight: 100 }];
  store.facts = ["x".repeat(100)];
  const ctx = await new Rail({ store, scope, maxContextChars: 80 }).recall("query");
  assert.equal(ctx.keystones.length, 1);
  assert.equal(ctx.facts.length, 0);
  assert.deepEqual(ctx.errors, ["facts_context_truncated"]);
});

test("request timeout remains active while reading the response body", async () => {
  const store = new RestMemoryStore({ tenantId: "tenant", timeoutMs: 10, fetch: async (_, init) => ({
    ok: true, status: 200, headers: new Headers(),
    json: () => new Promise((_, reject) => {
      init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
    }),
  }) });
  await assert.rejects(store.recall("query", scope), error =>
    error instanceof StoreError && error.retryable);
});

test("search limits match the server", async () => {
  const seen = [];
  const store = new RestMemoryStore({ tenantId: "tenant", fetch: async (_, init) => {
    seen.push(JSON.parse(init.body));
    return json({ items: [] });
  } });
  await store.recall("q".repeat(6000), scope, 20);
  assert.equal(seen[0].query.length, 5000);
  assert.equal(seen[0].top_k, 20);
  await assert.rejects(store.recall("query", scope, 21), /1 to 20/);
  assert.equal(seen.length, 1);
});
