# API reference

Both packages expose the same concepts. Python uses `snake_case`, synchronous
and asynchronous classes, and context managers. TypeScript uses `camelCase`,
promises, and callbacks. Argument validation errors raise `ValueError` in Python
and `TypeError` in TypeScript; backend failures raise `StoreError` in both.

Contents: [MemoryScope](#memoryscope), [Rail and AsyncRail](#rail-and-asyncrail),
[Turn results](#turn-results), [RecallContext](#recallcontext),
[WriteResult](#writeresult), [Stores](#stores), [StoreError](#storeerror),
[Outbox](#outbox), [Telemetry](#telemetry), [Extractors](#extractors),
[Constants](#constants), [Error and status vocabulary](#error-and-status-vocabulary).

## MemoryScope

Identity attached to every recall and write. Immutable.

Python: `MemoryScope(agent_id, tenant_id=None, fleet_id=None, visibility=Visibility.AGENT)`
TypeScript: `new MemoryScope({ agentId, tenantId?, fleetId?, visibility? })`

| Field | Type | Rules |
|---|---|---|
| `agent_id` / `agentId` | string | Required, nonempty. |
| `tenant_id` / `tenantId` | string or unset | Nonempty when set. Must equal the store's configured or discovered tenant, otherwise recall and write raise `StoreError`. |
| `fleet_id` / `fleetId` | string or unset | Nonempty when set. Sent as `fleet_ids` on search, `fleet_id` on write and rule lookup. |
| `visibility` | `Visibility.AGENT` \| `TEAM` \| `ORG` (Python), `"scope_agent"` \| `"scope_team"` \| `"scope_org"` (TypeScript) | Default agent-private. Team visibility requires a fleet. |

`for_agent(agent_id)` / `forAgent(agentId)` returns a copy for another agent.

`Visibility` is a Python `str` enum whose values are the wire strings above.

## Rail and AsyncRail

Python: `Rail(store, scope, *, extractor=rule_extract, outbox=None, top_k=8, require_keystones=False, max_context_chars=16000, max_facts=16, max_fact_chars=4000)`
Python: `AsyncRail(...)` with the same arguments and an `AsyncMemoryStore`.
TypeScript: `new Rail({ store, scope, extractor?, outbox?, topK?, requireKeystones?, maxContextChars?, maxFacts?, maxFactChars? })`

| Option | Default | Meaning |
|---|---|---|
| `store` | required | A `MemoryStore` (or `AsyncMemoryStore` for `AsyncRail`). |
| `scope` | required | A `MemoryScope`. |
| `extractor` | `rule_extract` / `ruleExtract` | Maps `(message, reply)` to facts. See [Extractors](#extractors). |
| `outbox` | `Outbox()` with capacity 1,000 | Queue for deferred writes. |
| `top_k` / `topK` | 8 | Facts requested per recall. Positive integer; the REST store additionally caps it at 20. |
| `require_keystones` / `requireKeystones` | false | Stop the turn with `StoreError` when rules cannot be loaded completely. |
| `max_context_chars` / `maxContextChars` | 16,000 | Cap on `context.text` in characters (code points). Rules are kept; facts are dropped from the end. |
| `max_facts` / `maxFacts` | 16 | Most facts an extractor may return per turn. |
| `max_fact_chars` / `maxFactChars` | 4,000 | Longest fact an extractor may return. |

All limits must be positive integers.

### Methods

**`recall(query)`** → `RecallContext`. Loads rules and facts without running a
turn and without touching turn counters. Rule and recall failures are recorded in
`context.errors` unless `require_keystones` is set, in which case a rule failure
raises `StoreError`. Python `Rail.recall` is synchronous; `AsyncRail.recall` and
the TypeScript method return promises.

**`turn(message)`** (Python) → `Turn`, a `TurnResult` that is also a context
manager. On enter it increments `telemetry.turns_total` and recalls. On a clean
exit with `reply` set to a string it extracts and writes. If the block raises,
if `reply` is unset, or if `reply` is not a string, nothing is written. A
non-string reply raises `TypeError` on exit. `AsyncRail.turn` returns an
`AsyncTurn` for use with `async with`.

**`turn(message, agent)`** (TypeScript) → `Promise<TurnResult>`. Recalls, awaits
`agent(message, context)`, then extracts and writes. An agent that throws
propagates and nothing is written. A non-string reply throws `TypeError`.

**`run(message, agent)`** → the reply string. Convenience over `turn`. Python
`Rail.run` calls `agent(message, context)` synchronously; `AsyncRail.run` and the
TypeScript method accept sync or async agents.

**`flush_outbox(max_attempts=3)`** / **`flushOutbox(maxAttempts = 3)`** →
list of `WriteResult`. Takes every queued item and retries it once. Retryable
failures below the attempt limit are re-queued and reported as `deferred`;
otherwise the item is dropped, counted in `outbox.total_dropped`, and reported as
`dropped`. Non-`StoreError` exceptions and cancellation restore the unprocessed
remainder to the queue and propagate.

### Attributes

`outbox` (the `Outbox`), `telemetry` (the `Telemetry` counters). Python also
exposes `store`, `scope`, `extractor`, and the limits as plain attributes.

## Turn results

`TurnResult` fields in both languages:

| Field | Type | Meaning |
|---|---|---|
| `context` | `RecallContext` | What was recalled before the agent ran. |
| `reply` | string; `None` until set in Python, `""` until set in TypeScript | The agent's reply. |
| `writes` | list of `WriteResult` | One per extracted fact, in extraction order. |
| `errors` | list of strings | Turn-level diagnostics, see [vocabulary](#error-and-status-vocabulary). |
| `degraded` | boolean | `context.degraded or errors nonempty`. |

Python's `Turn` and `AsyncTurn` subclasses add the context-manager protocol and
are what `Rail.turn` / `AsyncRail.turn` return.

## RecallContext

| Member | Type | Meaning |
|---|---|---|
| `keystones` | list of `KeystoneRule` (`doc_id`/`docId`, `title`, `content`, `weight`) | Sorted by weight, highest first. |
| `facts` | list of `Fact` (`id`, `content`, `agent_id`/`agentId`) | In the order the server returned them. |
| `errors` | list of strings | `keystones: <message>`, `recall: <message>`, `governance_context_overflow`, `facts_context_truncated`. |
| `degraded` | boolean | `errors` is nonempty. |
| `text` | string | `### GOVERNANCE RULES` section with `- title: content` lines, blank line, `### RECALLED MEMORY` section with `- content` lines. Sections are omitted when empty; the whole string is empty when nothing was recalled. |

## WriteResult

| Field | Meaning |
|---|---|
| `status` | `written`, `deduplicated`, `deferred`, `rejected`, or `dropped` (replay only). |
| `id` | The memory id for `written` and `deduplicated`. |
| `error` | The `StoreError` message for `deferred`, `rejected`, and `dropped`. |

## Stores

### RestMemoryStore and AsyncRestMemoryStore

Clients for the Caura REST API.

Python: `RestMemoryStore(base_url="http://localhost:8000", api_key="standalone", tenant_id=None, timeout=5.0, *, client=None)`
Python: `AsyncRestMemoryStore(...)` with an optional `httpx.AsyncClient`.
TypeScript: `new RestMemoryStore({ baseUrl?, apiKey?, tenantId?, timeoutMs?, fetch? })`

| Option | Default | Rules |
|---|---|---|
| `base_url` / `baseUrl` | `http://localhost:8000` | `http` or `https`; no credentials, query, or fragment. Trailing slash is removed. |
| `api_key` / `apiKey` | `standalone` | Nonempty. Sent as `X-API-Key`. |
| `tenant_id` / `tenantId` | unset | Nonempty when set. When unset, discovered once from `GET /api/v1/whoami` and cached on the store. |
| `timeout` / `timeoutMs` | 5 seconds / 5,000 ms | Positive and finite. Applies per HTTP request, including reading the body. |
| `client` (Python) | a new `httpx.Client` / `httpx.AsyncClient` | A supplied client is not closed by the store. |
| `fetch` (TypeScript) | `globalThis.fetch` | Injectable for tests. |

`from_env(**overrides)` / `fromEnv(env, overrides?)` read `CAURA_URL`,
`CAURA_API_KEY`, and `CAURA_TENANT` and apply any overrides.

Methods, all raising `StoreError` on backend failure:

- `recall(query, scope, top_k=8)` → list of `Fact`. `POST /api/v1/search` with
  `tenant_id`, `query` (truncated to 5,000 characters), `caller_agent_id`,
  `top_k` (1 to 20), and `fleet_ids` when the scope has a fleet.
- `keystones(scope)` → list of `KeystoneRule`. `GET /api/v1/keystones` with
  `tenant_id`, `agent_id`, and `fleet_id` when present. Accepts a bare array or an
  `items` envelope. A response flagged `X-Truncated: true` raises `StoreError`.
- `write(fact, scope)` → `WriteResult`. `POST /api/v1/memories` with `tenant_id`,
  `agent_id`, `content`, `visibility`, `write_mode: "strong"`, and `fleet_id`
  when present. Returns `written` with the new id, or `deduplicated` with the
  existing id when the server answers HTTP 409 with error code `DUPLICATE_MEMORY`
  and reason `exact_content_hash` or `semantic_similarity`.
- Python `close()` / `aclose()`, also via `with` / `async with`. The store closes
  only clients it created.

Responses are validated: missing or mistyped fields raise `StoreError` rather than
being treated as empty results. Response bodies never appear in error messages.

### Your own store

Python `MemoryStore` and `AsyncMemoryStore` are `typing.Protocol`s; TypeScript
`MemoryStore` is an interface. Implement:

- `recall(query, scope, top_k)` → list of `Fact`
- `keystones(scope)` → list of `KeystoneRule`
- `write(fact, scope)` → `WriteResult`

Raise `StoreError` for backend failures and set `retryable` for temporary ones.
In TypeScript, non-`StoreError` exceptions from a store propagate out of the turn.

## StoreError

Python: `StoreError(message, *, status=None, retryable=False)`, a `RuntimeError`.
TypeScript: `new StoreError(message, status?, retryable = false)`, an `Error` with
`name === "StoreError"`.

| Field | Meaning |
|---|---|
| `status` | HTTP status when the failure came from a response. |
| `retryable` | `true` for transport failures, HTTP 408, 429, and 5xx, and a duplicate race whose winner is no longer live. |

## Outbox

Python: `Outbox(capacity=1000)`; TypeScript: `new Outbox(capacity = 1000)`.
Capacity must be a positive integer.

| Member | Meaning |
|---|---|
| `capacity` | Maximum queued items. |
| `len(outbox)` / `size` | Items currently queued. |
| `total_dropped` / `totalDropped` | Items lost to capacity eviction or exhausted replay attempts. Never reset. |

Rail fills and drains the outbox; applications only read it and call
`flush_outbox` / `flushOutbox`.

## Telemetry

Process-local counters on `rail.telemetry`, never reset:

| Python | TypeScript | Increments when |
|---|---|---|
| `turns_total` | `turnsTotal` | A turn starts. |
| `degraded_turns` | `degradedTurns` | A turn ends degraded, including one stopped by `require_keystones`. Counted once per turn. |
| `writes_deferred` | `writesDeferred` | A write is queued. |
| `writes_rejected` | `writesRejected` | A write fails permanently. |
| `extraction_failures` | `extractionFailures` | The extractor raised or returned invalid output. |

## Extractors

Python `Extractor = Callable[[str, str], list[str]]`; `AsyncExtractor` may also
return an awaitable. TypeScript `Extractor = (message, reply) => string[] | Promise<string[]>`.
Agent callbacks are typed `Agent` / `AsyncAgent` in Python and `Agent` in TypeScript.

`rule_extract(message, reply)` / `ruleExtract(message, reply)` is the default. It
returns user lines beginning with `Remember:` (prefix removed), `We use`,
`We deploy`, `Our plan`, or `Our contract`, case-insensitive, deduplicated, in
order. The reply is ignored.

## Constants

Python `caura_rail.store.MAX_TOP_K = 20` and `MAX_QUERY_CHARS = 5000`; TypeScript
exports `MAX_TOP_K` and `MAX_QUERY_CHARS`. Python also exposes `__version__`.

## Error and status vocabulary

`turn.errors` values:

| Value | Meaning |
|---|---|
| `extraction_failed` | The extractor raised, returned a non-list, too many facts, a non-string, or an over-long fact. |
| `deferred` | A write was queued for replay. One entry per write. |
| `rejected` | A write failed permanently. One entry per write. |
| `governance_unavailable` (TypeScript only) | Recorded before a `StoreError` from recall propagates out of `turn`. |

`context.errors` values: `keystones: <message>`, `recall: <message>`,
`governance_context_overflow`, `facts_context_truncated`.

`StoreError` messages produced by the REST stores: `Caura request failed (HTTP <code>)`,
`Caura transport failure`, `Duplicate winner no longer live`,
`Backend returned truncated governance rules`, `Scope tenant does not match the
store tenant`, `Governance rules exceed the context budget`, and
`Invalid backend response: ...` variants.
