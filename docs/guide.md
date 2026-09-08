# Guide

This guide takes you from an empty project to an agent that recalls governance
rules and facts before every turn and stores new facts afterwards. Every code
block runs and type-checks in CI against a fixture that mirrors the Caura REST
contract, so you can paste it as written.

Contents: [Install](#install), [Connect a backend](#connect-a-backend),
[Your first turn](#your-first-turn), [Feed context to your model](#feed-context-to-your-model),
[Choose a scope](#choose-a-scope), [Control what gets stored](#control-what-gets-stored),
[Governance rules](#governance-rules), [Degraded turns and replay](#degraded-turns-and-replay),
[Async Python](#async-python), [Bring your own store](#bring-your-own-store),
[Verify against a live server](#verify-against-a-live-server),
[Troubleshooting](#troubleshooting).

## Install

```bash
python -m pip install caura-rail     # Python 3.10+
npm install @caura/rail              # Node.js 22+
```

## Connect a backend

Rail talks to the Caura REST API with an API key header and a tenant header. The
`from_env` / `fromEnv` constructors read:

| Variable | Required | Meaning |
|---|---|---|
| `CAURA_URL` | Yes | Base URL of the API. `https://caura.ai` for managed Caura. Defaults to `http://localhost:8000`. |
| `CAURA_API_KEY` | Yes | Sent as `X-API-Key`. Defaults to `standalone`. |
| `CAURA_TENANT` | No | Sent as `X-Tenant-ID` and in request bodies. When unset, Rail calls `GET /api/v1/whoami` once and uses the tenant the server reports for the key. |

Rail reads the environment only when you construct a store. It never loads `.env`
files. You can also pass values directly, which is what tests and multi-tenant
services usually do:

```python
from caura_rail import RestMemoryStore
import os

store = RestMemoryStore(
    base_url=os.environ["CAURA_URL"],
    api_key=os.environ["CAURA_API_KEY"],
    tenant_id="example-tenant",  # optional; skips discovery
    timeout=15.0,  # seconds per HTTP request
)
store.close()
```

```ts
import { RestMemoryStore } from "@caura/rail";

const store = new RestMemoryStore({
  baseUrl: process.env.CAURA_URL,
  apiKey: process.env.CAURA_API_KEY,
  tenantId: "example-tenant", // optional; skips discovery
  timeoutMs: 15000,           // per HTTP request
});
void store;
```

### Managed Caura

Set `CAURA_URL=https://caura.ai` and `CAURA_API_KEY` to a key from your Caura
account. Leave `CAURA_TENANT` unset unless your key can read several tenants and
you want to pin one.

### Self-hosted Caura

Follow the [Caura self-hosting guide](https://github.com/caura-ai/caura#quickstart).
The short version:

```bash
git clone https://github.com/caura-ai/caura.git && cd caura
docker compose up -d --wait          # Postgres with pgvector, Redis, storage API, core API on :8000
export CAURA_URL=http://localhost:8000 CAURA_API_KEY=standalone
```

The default compose file runs the server in standalone mode: one tenant named
`default` and no API key check. Rail discovers the `default` tenant by itself.
If you set `CAURA_API_KEY` on the server, use the same value in the client.

**Configure a real embedding provider before judging recall.** Out of the box
the server uses a hash-based placeholder embedder (`EMBEDDING_PROVIDER=fake`)
that only matches facts sharing literal words with the query. It keeps the
quick start free of API keys, but it is not how Caura recalls in production:
a query about "weather" will not find "heavy rain". For realistic recall,
create `.env` next to the compose file before starting:

```bash
cat > .env <<'EOF'
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
EOF
docker compose up -d --wait
```

The server's `.env.example` lists the alternatives, including a local
open-source embedding model behind the `embed-local` compose profile. Managed
Caura always uses real embeddings.

## Your first turn

A turn wraps one user message. Rail recalls before your code runs and writes
after it finishes cleanly.

```python
from caura_rail import MemoryScope, Rail, RestMemoryStore

scope = MemoryScope(agent_id="onboarding-bot")

with RestMemoryStore.from_env() as store:
    rail = Rail(store, scope)
    with rail.turn("Remember: We use Terraform for all infrastructure.") as turn:
        turn.reply = "Got it."
    # "written" the first time; "deduplicated" when the fact already exists.
    assert turn.writes[0].status in ("written", "deduplicated")
    assert turn.writes[0].id is not None

    # The next turn recalls it. Recall is semantic: ask about the topic.
    with rail.turn("What do we use for infrastructure?") as turn:
        assert "Terraform" in turn.context.text
        turn.reply = "You use Terraform."
    assert turn.writes == []  # a question is not a fact
```

```ts
import assert from "node:assert/strict";
import { MemoryScope, Rail, RestMemoryStore } from "@caura/rail";

const rail = new Rail({
  store: RestMemoryStore.fromEnv(process.env),
  scope: new MemoryScope({ agentId: "onboarding-bot" }),
});

const first = await rail.turn("Remember: We use Terraform for all infrastructure.", () => "Got it.");
// "written" the first time; "deduplicated" when the fact already exists.
assert.ok(["written", "deduplicated"].includes(first.writes[0]?.status ?? ""));

const second = await rail.turn("What do we use for infrastructure?", (_, context) => {
  assert.match(context.text, /Terraform/);
  return "You use Terraform.";
});
assert.deepEqual(second.writes, []);
```

The Python `turn` is a context manager because your code runs in the middle. Set
`turn.reply` before the block ends; if you leave it unset or raise, Rail writes
nothing. The TypeScript `turn` takes your agent as a callback and returns a
`TurnResult` once writes are done. Both offer `run(message, agent)` when you only
want the reply string.

Memory is persistent, so a fact your program stores on its first run is already
there on the second. The server answers a repeated write with `deduplicated` and
the existing memory's `id`. Treat `written` and `deduplicated` as the same
success when your code checks write results; only `rejected` and `deferred` need
attention.

## Feed context to your model

`turn.context.text` is prompt-ready. Rules come first under a
`### GOVERNANCE RULES` heading, then facts under `### RECALLED MEMORY`. When
nothing was recalled it is an empty string, so you can append it unconditionally.

```python
from caura_rail import MemoryScope, Rail, RecallContext, RestMemoryStore


def call_model(system: str, user: str) -> str:
    # Replace with your model client.
    return f"[system {len(system)} chars] {user}"


def agent(message: str, context: RecallContext) -> str:
    system = "You are a support agent.\n\n" + context.text
    return call_model(system, message)


with RestMemoryStore.from_env() as store:
    rail = Rail(store, MemoryScope(agent_id="support-1", fleet_id="support"))
    print(rail.run("Where do we deploy?", agent))
```

If you need the structured pieces instead of the text, read `context.keystones`
(rules with `title`, `content`, `weight`) and `context.facts` (`id`, `content`,
`agent_id`).

### Getting the facts you need

Recall is semantic search over the user's message, limited to `top_k` results
(default 8, at most 20). A broad message such as "what is the plan?" ranks
against every stored fact, so specific facts can fall outside the top results.
Two practices keep recall reliable:

- Ask specific questions and raise `top_k` for assistants that need a wide view.
- When a turn must have a particular kind of fact, run a focused `recall(query)`
  for it before the turn and combine the two contexts yourself. `recall` does not
  count as a turn and writes nothing.

```python
from caura_rail import MemoryScope, Rail, RestMemoryStore

with RestMemoryStore.from_env() as store:
    rail = Rail(store, MemoryScope(agent_id="liaison", fleet_id="ops"), top_k=12)
    policy = rail.recall("boarding policy for passengers with reduced mobility")
    with rail.turn("Can I get to Harbor before 17:00?") as turn:
        facts = {f.id: f for f in turn.context.facts + policy.facts}  # merge, deduplicate by id
        turn.reply = f"Considering {len(facts)} facts.\n" + turn.context.text
```

`RecallContext.text` and `degraded` are computed from `facts` and `keystones`.
Build a new context from merged facts rather than copying the object: in
TypeScript, spreading a `RecallContext` into a plain object drops those
computed properties.

The context is capped at `max_context_chars` (default 16,000 characters). Rail
keeps every rule and drops facts from the end until the text fits, recording
`facts_context_truncated` in `context.errors`. If the rules alone exceed the cap,
they are dropped with `governance_context_overflow`, unless `require_keystones`
is set, in which case the turn stops with a `StoreError`.

## Choose a scope

`MemoryScope` names the caller and says who should be able to recall what it
writes. The server enforces access; the scope describes intent.

| Field | Meaning |
|---|---|
| `agent_id` / `agentId` | Required. The writing and recalling agent. |
| `fleet_id` / `fleetId` | Optional. A team of agents that share memory. |
| `visibility` | `AGENT` / `"scope_agent"` (default): only this agent recalls it. `TEAM` / `"scope_team"`: agents in the fleet; requires a fleet. `ORG` / `"scope_org"`: every agent in the tenant. |
| `tenant_id` / `tenantId` | Optional. Must match the store's configured or discovered tenant. |

Use `for_agent` / `forAgent` to reuse a scope for another agent in the same fleet:

```python
from caura_rail import MemoryScope, Rail, RestMemoryStore, Visibility

team = MemoryScope(agent_id="writer", fleet_id="support", visibility=Visibility.TEAM)
with RestMemoryStore.from_env() as store:
    Rail(store, team).run("Remember: Our contract with Acme renews in March.", lambda *_: "Noted.")
    reader = Rail(store, team.for_agent("reader"))
    context = reader.recall("When does the Acme contract renew?")
    assert any("Acme" in fact.content for fact in context.facts)
```

`rail.recall(query)` fetches context without running a turn and without touching
the turn counters. It is the right call for a read-only lookup.

## Control what gets stored

The extractor decides which facts a turn writes. It receives the user message and
the reply and returns a list of strings. The default, `rule_extract`, keeps user
lines that begin with `Remember:`, `We use`, `We deploy`, `Our plan`, or
`Our contract`. It does not judge whether they are true.

Supply your own for application-specific extraction. Return an empty list to make
Rail recall-only.

```python
from caura_rail import MemoryScope, Rail, RestMemoryStore


def preferences_only(message: str, reply: str) -> list[str]:
    lowered = message.lower()
    if lowered.startswith("i prefer"):
        return ["User preference: " + message[len("I prefer") :].strip()]
    return []


with RestMemoryStore.from_env() as store:
    rail = Rail(store, MemoryScope(agent_id="assistant"), extractor=preferences_only)
    with rail.turn("I prefer short answers.") as turn:
        turn.reply = "Sure."
    assert len(turn.writes) == 1 and turn.writes[0].status in ("written", "deduplicated")

    recall_only = Rail(store, MemoryScope(agent_id="assistant"), extractor=lambda *_: [])
    with recall_only.turn("Remember: this will not be stored.") as turn:
        turn.reply = "Okay."
    assert turn.writes == []
```

```ts
import assert from "node:assert/strict";
import { MemoryScope, Rail, RestMemoryStore } from "@caura/rail";

const preferencesOnly = (message: string, _reply: string): string[] =>
  /^i prefer/i.test(message) ? ["User preference: " + message.slice("I prefer".length).trim()] : [];

const store = RestMemoryStore.fromEnv(process.env);
const rail = new Rail({ store, scope: new MemoryScope({ agentId: "assistant" }), extractor: preferencesOnly });
const turn = await rail.turn("I prefer short answers.", () => "Sure.");
assert.equal(turn.writes.length, 1);
assert.ok(["written", "deduplicated"].includes(turn.writes[0]?.status ?? ""));
```

Rules that keep extraction safe:

- Rail validates the extractor's output. It must be a list of at most `max_facts`
  strings (default 16), each at most `max_fact_chars` characters (default 4,000).
  Anything else, or an exception, records `extraction_failed` in `turn.errors`,
  increments `telemetry.extraction_failures`, and writes nothing. The reply is
  still returned.
- Facts are trimmed and deduplicated within a turn before writing.
- The server requires stored content to be 10 to 10,000 characters. Shorter facts
  come back as `rejected` with HTTP 422.
- A fact identical to an existing memory in the same scope comes back as
  `deduplicated` with the existing memory's `id`.
- Async extractors are supported by `AsyncRail` and by the TypeScript `Rail`. The
  synchronous Python `Rail` treats a coroutine as an extraction failure.

## Governance rules

Keystones are rules your organization stores in Caura. Rail fetches them on every
recall, sorts them by weight (100, 50, 25 for high, medium, low), and puts them
ahead of facts in the context. Rules scoped to an agent are returned only when the
scope also names a fleet.

Rail reads rules; it does not write them. Create and remove them with the Caura
API (or the UI on managed Caura). One rule for a fleet, using the same key and
tenant your Rail store uses:

```bash
curl -X POST "$CAURA_URL/api/v1/keystones" \
  -H "X-API-Key: $CAURA_API_KEY" -H "X-Tenant-ID: default" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "default", "fleet_id": "ops", "doc_id": "eu-residency",
       "title": "Residency", "content": "Keep customer data in the EU.",
       "scope": "fleet", "weight": "high"}'

curl -X DELETE "$CAURA_URL/api/v1/keystones/eu-residency?tenant_id=default&fleet_id=ops" \
  -H "X-API-Key: $CAURA_API_KEY" -H "X-Tenant-ID: default"
```

`scope` is `tenant`, `fleet`, or `agent` (agent rules also need `agent_id`);
`weight` is `low`, `med`, or `high`; `doc_id` is a lowercase slug and is the id
you delete by. Replace `default` with your tenant on multi-tenant deployments.

Rules are authored by an agent the server trusts. A standalone server lets any
key act as any agent: add an `X-Agent-ID` header naming an agent that has
written at least one memory, and raise that agent's trust to 2 with
`PATCH /api/v1/agents/<agent_id>/trust?tenant_id=<tenant>` and body
`{"trust_level": 2}` before creating rules. On managed and multi-tenant Caura
the gateway decides the acting agent from the credential and ignores the
header, so author rules with an agent-scoped credential issued for that agent
(trust level 2 or higher), or in the Caura dashboard. Reading rules needs no
special credential; every Rail scope receives them.
After that, `rail.recall(...)` for any agent in fleet `ops` starts with
`### GOVERNANCE RULES` followed by `- Residency: Keep customer data in the EU.`

By default a failure to load rules degrades the turn but lets the agent run. Set
`require_keystones` / `requireKeystones` when the agent must not run without
them:

```python
from caura_rail import MemoryScope, Rail, RestMemoryStore, StoreError

with RestMemoryStore(
    base_url="http://127.0.0.1:9", api_key="x", tenant_id="t", timeout=0.5
) as store:
    rail = Rail(store, MemoryScope(agent_id="regulated"), require_keystones=True)
    try:
        rail.run("Any message", lambda *_: "never runs")
    except StoreError as error:
        print("stopped before the agent ran:", error)
    assert rail.telemetry.degraded_turns == 1
```

An empty rules response is valid and does not trigger the requirement. A
response the server marks as truncated (more than 50 matching rules) is treated
as a failure, because the agent would be missing rules it should follow.

## Degraded turns and replay

Rail separates your agent's failures from memory failures:

- If your agent raises, the exception propagates and nothing is written.
- If recall fails, the turn is degraded, `context.errors` says why, and your agent
  runs with whatever was recalled.
- If a write fails with a temporary error (transport failure, HTTP 408, 429, or
  5xx, or a duplicate race the server asks you to retry), the fact is
  `deferred` into an in-memory outbox. Authentication, permission, validation,
  and unknown conflicts are `rejected` and never retried.

Replay the outbox when connectivity returns. There is no background timer; you
decide when.

```python
from caura_rail import MemoryScope, Rail, RestMemoryStore

with RestMemoryStore(
    base_url="http://127.0.0.1:9", api_key="x", tenant_id="t", timeout=0.5
) as offline:
    rail = Rail(offline, MemoryScope(agent_id="field-agent"))
    with rail.turn("Remember: The site visit moved to Thursday.") as turn:
        turn.reply = "Rescheduled."
    assert turn.degraded and turn.writes[0].status == "deferred"
    assert len(rail.outbox) == 1

    # Later, once the backend is reachable, replay. Each item gets up to max_attempts tries.
    results = rail.flush_outbox(max_attempts=3)
    print([r.status for r in results])  # still offline here, so: ['deferred']
```

```ts
import assert from "node:assert/strict";
import { MemoryScope, Rail, RestMemoryStore } from "@caura/rail";

const offline = new RestMemoryStore({ baseUrl: "http://127.0.0.1:9", apiKey: "x", tenantId: "t", timeoutMs: 500 });
const rail = new Rail({ store: offline, scope: new MemoryScope({ agentId: "field-agent" }) });
const turn = await rail.turn("Remember: The site visit moved to Thursday.", () => "Rescheduled.");
assert.equal(turn.degraded, true);
assert.equal(turn.writes[0]?.status, "deferred");
assert.equal(rail.outbox.size, 1);

const results = await rail.flushOutbox(3);
console.log(results.map(r => r.status)); // still offline here, so: [ 'deferred' ]
```

The outbox holds 1,000 items by default. Pass `Outbox(capacity)` /
`new Outbox(capacity)` to change it. When full, the oldest item is dropped and
`outbox.total_dropped` / `outbox.totalDropped` increments. Pending items are lost
when the process exits; see [Reliability](reliability.md) for the full semantics.

## Async Python

`AsyncRail` and `AsyncRestMemoryStore` mirror the synchronous API with `async`
context managers, async agents, and async extractors:

```python
import asyncio

from caura_rail import AsyncRail, AsyncRestMemoryStore, MemoryScope, RecallContext


async def agent(message: str, context: RecallContext) -> str:
    await asyncio.sleep(0)
    return "Handled with %d rule(s)." % len(context.keystones)


async def extractor(message: str, reply: str) -> list[str]:
    return [message] if message.startswith("Remember:") else []


async def main() -> None:
    async with AsyncRestMemoryStore.from_env() as store:
        rail = AsyncRail(store, MemoryScope(agent_id="async-bot"), extractor=extractor)
        message = "Remember: Our plan ships weekly on Tuesdays."
        async with rail.turn(message) as turn:
            turn.reply = await agent(message, turn.context)
        print(turn.reply, [w.status for w in turn.writes])
        print(await rail.run("Anything pending?", agent))


asyncio.run(main())
```

Use one `Rail` and one store per worker or event loop. The outbox guards its own
queue operations, but the rest of a `Rail` is not shared across threads.

## Bring your own store

`Rail` accepts anything that implements the store interface: `MemoryStore` or
`AsyncMemoryStore` in Python, `MemoryStore` in TypeScript. This is how you test
without a server or adapt Rail to another backend. Raise `StoreError` for backend
failures and mark temporary ones `retryable` so the outbox can replay them.

```python
from caura_rail import Fact, KeystoneRule, MemoryScope, Rail, StoreError, WriteResult


class ListStore:
    """A tiny in-process store. Satisfies caura_rail.MemoryStore."""

    def __init__(self) -> None:
        self.rows: list[Fact] = []
        self.offline = False

    def keystones(self, scope: MemoryScope) -> list[KeystoneRule]:
        return [KeystoneRule("tone", "Tone", "Be concise.", 100)]

    def recall(self, query: str, scope: MemoryScope, top_k: int = 8) -> list[Fact]:
        words = set(query.lower().split())
        return [f for f in self.rows if words & set(f.content.lower().split())][:top_k]

    def write(self, fact: str, scope: MemoryScope) -> WriteResult:
        if self.offline:
            raise StoreError("store offline", retryable=True)
        self.rows.append(Fact(str(len(self.rows) + 1), fact, scope.agent_id))
        return WriteResult("written", id=self.rows[-1].id)


store = ListStore()
rail = Rail(store, MemoryScope(agent_id="test"))
assert (
    rail.run("Remember: We deploy on Fridays.", lambda m, c: c.text)
    == "### GOVERNANCE RULES\n- Tone: Be concise."
)
assert "Fridays" in rail.recall("When do we deploy?").text
```

```ts
import assert from "node:assert/strict";
import { MemoryScope, Rail, StoreError } from "@caura/rail";
import type { Fact, KeystoneRule, MemoryStore, WriteResult } from "@caura/rail";

class ListStore implements MemoryStore {
  rows: Fact[] = [];
  offline = false;
  async keystones(): Promise<KeystoneRule[]> {
    return [{ docId: "tone", title: "Tone", content: "Be concise.", weight: 100 }];
  }
  async recall(query: string, _scope: MemoryScope, topK = 8): Promise<Fact[]> {
    const words = new Set(query.toLowerCase().split(" "));
    return this.rows.filter(f => f.content.toLowerCase().split(" ").some(w => words.has(w))).slice(0, topK);
  }
  async write(fact: string, scope: MemoryScope): Promise<WriteResult> {
    if (this.offline) throw new StoreError("store offline", undefined, true);
    this.rows.push({ id: String(this.rows.length + 1), content: fact, agentId: scope.agentId });
    return { status: "written", id: this.rows.at(-1)!.id };
  }
}

const rail = new Rail({ store: new ListStore(), scope: new MemoryScope({ agentId: "test" }) });
assert.equal(await rail.run("Remember: We deploy on Fridays.", (_, c) => c.text), "### GOVERNANCE RULES\n- Tone: Be concise.");
assert.match((await rail.recall("When do we deploy?")).text, /Fridays/);
```

## Verify against a live server

The repository ships two verification programs:

- `contracts/smoke.py` runs both packages against a local fixture that mirrors
  the Caura REST contract. It needs no account and writes nothing real.
- `contracts/live.py` runs both packages against a real backend named by the
  environment variables above. It creates and removes two rules in fleet
  `rail-live` and writes a few uniquely marked facts. CI runs it against the
  open-source Caura release listed in the README.

```bash
export CAURA_URL=http://localhost:8000 CAURA_API_KEY=standalone
python contracts/live.py
```

## Troubleshooting

| Symptom | Meaning | What to do |
|---|---|---|
| `context.errors` contains `keystones: Caura request failed (HTTP 404)` and `recall: ... (HTTP 404)` | `CAURA_URL` points at something that is not the Caura API root. | Use the API base URL without a path, for example `http://localhost:8000`. |
| `StoreError: Caura request failed (HTTP 401)` | The API key was rejected. | Check `CAURA_API_KEY`. Self-hosted servers with a configured key require the same value. |
| The first call of a process is `deferred` or `recall: Caura transport failure`, later calls succeed | Behind the Caura gateway the first identity resolution for a key can take several seconds while services warm up. | Set `CAURA_TENANT` so Rail skips identity discovery, or raise the store timeout above the 15-second default (`timeout=30` in Python, `timeoutMs: 30000` in TypeScript). |
| Write `rejected` with HTTP 403 mentioning `fleet-scope policy` | The agent already belongs to another fleet. | Use one agent id per fleet. See [Choose a scope](#choose-a-scope). |
| `HTTP 403` | The key cannot read the tenant you named. | Unset `CAURA_TENANT` to use the key's own tenant, or use a key authorized for it. |
| `StoreError: Scope tenant does not match the store tenant` | `MemoryScope.tenant_id` differs from the store's configured or discovered tenant. | Drop the scope tenant or align the two. |
| `WriteResult(status="rejected", error="Caura request failed (HTTP 422)")` | The server refused the content, usually shorter than 10 characters or longer than 10,000. | Adjust the extractor. |
| `status="deduplicated"` | An identical memory already exists; `id` points at it. | Nothing. This is success. |
| `status="deferred"` and the turn is degraded | A temporary failure; the fact is queued. | Call `flush_outbox()` / `flushOutbox()` when the backend is reachable. |
| `ValueError: top_k must be an integer from 1 to 20` | The server caps search results at 20. | Lower `top_k` / `topK`. |
| `TypeError: Agent reply must be a string; use AsyncRail for async agents` | An `async def` agent was passed to the synchronous `Rail`. | Use `AsyncRail`, or return a string. |
| Rail does not log anything | By design. Rail never logs fact content or response bodies. | Log `turn.errors` and `rail.telemetry` from your application. |
