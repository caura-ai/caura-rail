<h1 align="center">Caura Rail</h1>

<h3 align="center">Memory around every agent turn &mdash; for Python and TypeScript.</h3>

<p align="center">
  Before your agent runs, Rail fetches the governance rules and the facts relevant to the current
  message from <a href="https://caura.ai">Caura</a>. After the agent replies, Rail extracts the facts
  worth keeping and writes them back. Your code stays in charge of the model call.
</p>

<p align="center">
  <a href="https://pypi.org/project/caura-rail/"><img src="https://img.shields.io/pypi/v/caura-rail?label=PyPI&color=0E6B5A" alt="PyPI" /></a>
  <a href="https://www.npmjs.com/package/@caura/rail"><img src="https://img.shields.io/npm/v/%40caura%2Frail?label=npm&color=0E6B5A" alt="npm" /></a>
  <a href="https://github.com/caura-ai/caura-rail/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/caura-ai/caura-rail/ci.yml?label=CI" alt="CI" /></a>
  <a href="https://pypi.org/project/caura-rail/"><img src="https://img.shields.io/pypi/pyversions/caura-rail?label=Python" alt="Python versions" /></a>
  <a href="https://www.npmjs.com/package/@caura/rail"><img src="https://img.shields.io/node/v/%40caura%2Frail?label=Node.js" alt="Node.js version" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License" /></a>
</p>

<p align="center">
  <a href="#install">Install</a> &middot;
  <a href="#connect-to-caura">Connect</a> &middot;
  <a href="#python">Python</a> &middot;
  <a href="#typescript-and-javascript">TypeScript</a> &middot;
  <a href="#how-a-turn-works">How a turn works</a> &middot;
  <a href="docs/guide.md">Guide</a> &middot;
  <a href="docs/api.md">API reference</a> &middot;
  <a href="#compatibility">Compatibility</a>
</p>

---

## Why Rail

Caura is shared, governed memory for fleets of AI agents. Its REST clients,
`caura-client` and `@caura/client`, call that API one request at a time. Rail
sits one level up: it wraps each **turn** of an agent you write yourself.

| | Thin client (`caura-client`, `@caura/client`) | Rail (`caura-rail`, `@caura/rail`) |
|---|---|---|
| You want to | call a Caura endpoint | give an agent memory it uses on every turn |
| Rules | fetch them yourself | fetched first and placed ahead of facts, every turn |
| Facts | search and write yourself | recalled before the agent runs, extracted and written after |
| Failures | your code decides | classified: `written`, `deduplicated`, `deferred` with replay, `rejected` |
| Languages | Python, TypeScript | Python (sync and async), TypeScript |

> **Use a client to call the API; use Rail to give an agent memory around every turn.**

Rail 1.0 is a stable release. Both packages carry the same semantics, are tested
against the same HTTP contract, and are exercised against a running Caura server
on every commit.

## Install

Python 3.10 or newer:

```bash
python -m pip install caura-rail
```

Node.js 22 or newer, TypeScript or JavaScript:

```bash
npm install @caura/rail
```

Both packages ship type information. The Python package depends on httpx; the
npm package has no runtime dependencies.

## Connect to Caura

Rail reads three environment variables when you call `RestMemoryStore.from_env()`
in Python or `RestMemoryStore.fromEnv(process.env)` in TypeScript.

| Variable | Managed Caura | Self-hosted Caura |
|---|---|---|
| `CAURA_URL` | `https://caura.ai` | Your server URL, for example `http://localhost:8000` |
| `CAURA_API_KEY` | Your API key | Your configured key, or any placeholder such as `standalone` when the server runs in standalone mode |
| `CAURA_TENANT` | Optional | Optional |

When `CAURA_TENANT` is unset, Rail asks the server who the key belongs to and uses
that tenant. A self-hosted server in standalone mode reports the tenant `default`.
See [Connect a backend](docs/guide.md#connect-a-backend) for the details, including
how to run Caura locally with Docker.

## Python

```python
from caura_rail import MemoryScope, Rail, RestMemoryStore, Visibility

scope = MemoryScope(agent_id="support-1", fleet_id="support", visibility=Visibility.TEAM)

with RestMemoryStore.from_env() as store:
    rail = Rail(store, scope)
    with rail.turn("Remember: We deploy in eu-west-1.") as turn:
        # Call your model here. turn.context.text holds rules first, then facts.
        turn.reply = "Understood. Context used:\n" + turn.context.text
    print(turn.reply)
    print("degraded:", turn.degraded, "writes:", [w.status for w in turn.writes])
```

Every turn does four things in order: recall, run your code, extract, write. If
your code raises, nothing is written. If the backend is unreachable, the turn is
marked degraded, your reply still returns, and retryable writes wait in an
in-memory outbox that you replay with `rail.flush_outbox()`.

Asynchronous applications use `AsyncRail` with `AsyncRestMemoryStore`:

```python
import asyncio

from caura_rail import AsyncRail, AsyncRestMemoryStore, MemoryScope, RecallContext


async def my_agent(message: str, context: RecallContext) -> str:
    return "Reply to: " + message  # Use context.text in your prompt.


async def main() -> None:
    scope = MemoryScope(agent_id="support-1")
    async with AsyncRestMemoryStore.from_env() as store:
        rail = AsyncRail(store, scope)
        reply = await rail.run("Remember: Our plan renews every March.", my_agent)
        print(reply)


asyncio.run(main())
```

## TypeScript and JavaScript

```ts
import { MemoryScope, Rail, RestMemoryStore } from "@caura/rail";

const scope = new MemoryScope({ agentId: "support-1", fleetId: "support", visibility: "scope_team" });
const store = RestMemoryStore.fromEnv(process.env);
const rail = new Rail({ store, scope });

const turn = await rail.turn("Remember: We deploy in eu-west-1.", async (message, context) => {
  // Call your model here. context.text holds rules first, then facts.
  return "Understood. Context used:\n" + context.text;
});
console.log(turn.reply);
console.log("degraded:", turn.degraded, "writes:", turn.writes.map(w => w.status));
```

The TypeScript API is asynchronous throughout. `rail.run(message, agent)` returns
only the reply; `rail.turn(message, agent)` returns the full result.

## How a turn works

```
                 your message
                      │
       ┌──────────────▼──────────────┐
   1.  │  RECALL                     │   GET  /api/v1/keystones   rules, heaviest first
       │  rules + relevant facts     │   POST /api/v1/search      facts, as this agent
       └──────────────┬──────────────┘
                      │  turn.context.text  (### GOVERNANCE RULES, then ### RECALLED MEMORY)
       ┌──────────────▼──────────────┐
   2.  │  YOUR AGENT                 │   any model, any framework; you set turn.reply
       └──────────────┬──────────────┘
                      │  if your code raises, nothing below runs
       ┌──────────────▼──────────────┐
   3.  │  EXTRACT                    │   default: user lines starting Remember:, We use, ...
       │  facts worth keeping        │   or your own extractor; [] makes Rail recall-only
       └──────────────┬──────────────┘
       ┌──────────────▼──────────────┐
   4.  │  WRITE                      │   POST /api/v1/memories, write_mode "strong"
       │  one result per fact        │   written · deduplicated · deferred → outbox · rejected
       └─────────────────────────────┘
```

## What you get on every turn

| On the turn | What it holds |
|---|---|
| `turn.context` | Governance rules sorted by weight, then recalled facts, plus `text` formatted for a prompt. Rules are never dropped to make room for facts. |
| `turn.writes` | One result per extracted fact: `written`, `deduplicated` (the fact already existed; `id` points at it), `deferred` (temporary failure, queued for `flush_outbox()`), or `rejected`. |
| `turn.errors`, `turn.degraded` | Why a turn was less than perfect, without the agent failing. |
| `rail.telemetry` | Process-local counters: turns, degraded turns, deferred and rejected writes, extraction failures. |

The default extractor stores user lines that begin with `Remember:`, `We use`,
`We deploy`, `Our plan`, or `Our contract`. Pass your own extractor to store
anything else, or return an empty list to make Rail recall-only.

## Documentation

| Read | When |
|---|---|
| [Guide](docs/guide.md) | Configuration, scopes and fleets, custom extraction, governance rules, degraded turns and replay, async Python, bringing your own store, troubleshooting. |
| [API reference](docs/api.md) | Every class, option, return value, and error, in both languages. |
| [Reliability](docs/reliability.md) | Failure classification, outbox and replay semantics, server limits, concurrency. |
| [Contract tests](contracts/README.md) | How both packages are verified against the Caura HTTP contract and against live servers. |
| [Changelog](CHANGELOG.md) &middot; [Security](SECURITY.md) &middot; [Contributing](CONTRIBUTING.md) | |

## Compatibility

| Component | Verified |
|---|---|
| Python | 3.10, 3.11, 3.12, 3.13, 3.14 |
| Node.js | 22, 24 |
| Caura server | Managed Caura, and open-source release backend-v2.47.0 or later. Earlier servers ignore the caller identity Rail asserts on search, so agents cannot recall their own private facts. |
| Embeddings | Recall quality depends on the server's embedding provider. The open-source quick start ships a placeholder embedder; see [Self-hosted Caura](docs/guide.md#self-hosted-caura). |

Every code block in this README and in `docs/` is executed twice and type-checked in
CI, against a contract fixture and against a live Caura server.

---

<p align="center">Licensed under <a href="LICENSE">Apache-2.0</a> &middot; Built by <a href="https://caura.ai">Caura</a></p>
