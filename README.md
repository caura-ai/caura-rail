# Caura Rail

Memory operations around agent turns, for Python and TypeScript/JavaScript.

Before your agent runs, Rail fetches the governance rules and relevant facts for
the current message from [Caura](https://caura.ai). After the agent replies, Rail
extracts facts worth keeping and writes them back. Your application stays in
charge of the model call: Rail hands you prompt-ready context and reports exactly
what was recalled, written, deferred, or rejected.

Rail is a stable 1.0 release. Both packages carry the same semantics and are
tested against the same HTTP contract and against a running Caura server.

Caura also publishes `caura-client` and `@caura/client`, thin clients for the
REST API. Use a client to call the API; use Rail to give an agent memory around
every turn.

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

## What you get on every turn

- **Context** in `turn.context`: governance rules sorted by weight, then recalled
  facts, plus `text` formatted for a prompt. Rules are never dropped to make room
  for facts.
- **Writes** in `turn.writes`: one result per extracted fact with status
  `written`, `deduplicated`, `deferred`, or `rejected`.
- **Diagnostics** in `turn.errors` and `turn.degraded`, and process-local counters
  in `rail.telemetry`.

The default extractor stores user lines that begin with `Remember:`, `We use`,
`We deploy`, `Our plan`, or `Our contract`. Pass your own extractor to store
anything else, or return an empty list to make Rail recall-only.

## Documentation

- [Guide](docs/guide.md): configuration, scopes, custom extraction, governance,
  outbox replay, bringing your own store, and troubleshooting.
- [API reference](docs/api.md): every class, option, return value, and error in
  both languages.
- [Reliability](docs/reliability.md): failure classification, replay semantics,
  and limits.
- [Contract tests](contracts/README.md): how the packages are verified against the
  Caura HTTP contract and against a live server.
- [Changelog](CHANGELOG.md), [Security](SECURITY.md), [Contributing](CONTRIBUTING.md).

## Compatibility

| Component | Verified |
|---|---|
| Python | 3.10, 3.11, 3.12, 3.13, 3.14 |
| Node.js | 22, 24 |
| Caura server | Managed Caura, and open-source release backend-v2.47.0 or later. Earlier servers ignore the caller identity Rail asserts on search, so agents cannot recall their own private facts. |
| Embeddings | Recall quality depends on the server's embedding provider. The open-source quick start ships a placeholder embedder; see [Self-hosted Caura](docs/guide.md#self-hosted-caura). |

Every code block in this README and in `docs/` is executed and type-checked in CI.

Licensed under [Apache-2.0](LICENSE).
