# Caura Rail

Memory operations around agent turns, for Python and TypeScript/JavaScript.
Rail fetches rules and relevant facts before your agent runs, then extracts
facts from a completed turn and writes them to [Caura](https://caura.ai).
Your application passes the recalled context into its agent.

**Development alpha.** The APIs can change. Packages are installed from source;
no registry release is available yet.

## Install from source

Python 3.10+:

    python -m pip install -e packages/python

TypeScript / JavaScript, Node.js 22+:

    npm ci
    npm run build

The npm workspace makes @caura/rail available to the repository examples.

## Python

    from caura_rail import MemoryScope, Rail, RestMemoryStore, Visibility

    scope = MemoryScope(
        agent_id="support-1",
        fleet_id="support",
        visibility=Visibility.TEAM,
    )
    with RestMemoryStore.from_env() as store:
        rail = Rail(store, scope)
        with rail.turn("Remember: We deploy in eu-west-1.") as turn:
            # Replace this with your agent, passing turn.context.text into its prompt.
            turn.reply = "Received context: " + turn.context.text
        print(turn.reply, turn.degraded, turn.writes)

For nonblocking memory I/O, use AsyncRail and AsyncRestMemoryStore with
async context managers:

    async with AsyncRestMemoryStore.from_env() as store:
        rail = AsyncRail(store, scope)
        async with rail.turn(message) as turn:
            turn.reply = await your_agent(message, turn.context.text)

Import those two async classes from caura_rail. The application supplies
message, scope, and your_agent in the second snippet.

## TypeScript and JavaScript

    import { MemoryScope, Rail, RestMemoryStore } from "@caura/rail";

    const scope = new MemoryScope({
      agentId: "support-1",
      fleetId: "support",
      visibility: "scope_team",
    });
    const rail = new Rail({
      store: RestMemoryStore.fromEnv(process.env),
      scope,
    });
    const turn = await rail.turn("Remember: We deploy in eu-west-1.", async (message, ctx) => {
      // Replace this with your agent and include ctx.text in its prompt.
      return "Received context: " + ctx.text;
    });
    console.log(turn.reply, turn.degraded, turn.writes);

Python rail.run(message, agent) and TypeScript rail.run(message, agent) return
only the reply. Use the turn API to inspect write outcomes and errors.

## Connect a backend

For managed Caura, export CAURA_URL=https://caura.ai and your CAURA_API_KEY.
For self-hosting, follow the [Caura Docker guide](https://caura.ai/docs/getting-started/self-host)
and point CAURA_URL at its API, commonly http://localhost:8000.
The default API key string is standalone; it only works with a backend explicitly
configured for standalone operation.

CAURA_TENANT is optional when the backend supports authenticated /whoami discovery.
Otherwise configure it explicitly. Environment variables are read at construction;
Rail does not search for or load .env files. A scope tenant must match a configured
or discovered store tenant. Neither an unavailable discovery endpoint nor invalid
credentials cause a silent fallback to a default tenant.

The live examples create one sample memory each. Run them against a test fleet
with credentials authorized for both example agents:

    python examples/fleet.py
    node examples/fleet.mjs

They require a real backend and fail if writing or recall is degraded. The
Python/TypeScript interoperability test in contracts/smoke.py uses a local HTTP
fixture instead; it needs no account and writes nothing to a real backend.

## Behavior and limits

- Python offers synchronous and asynchronous clients. TypeScript is asynchronous.
- Scope defaults to agent-private writes. Team visibility requires a fleet.
  Scope values describe identity and desired visibility; the server enforces access.
- Recall uses /api/v1/search for facts and /api/v1/keystones for rules. It does not
  request an LLM-generated recall summary.
- The default extractor recognizes user lines beginning with Remember:, We use,
  We deploy, Our plan, or Our contract. It does not verify their truth.
  Supply an extractor callback for application-specific extraction, or return an
  empty list to disable automatic writes. Async clients accept async extractors.
- Failed agent calls skip extraction and writes. Store errors are reported in the
  turn while the agent can continue. require_keystones=True / requireKeystones: true
  stops execution when rules cannot be loaded completely; an empty successful rules
  response is valid.
- The outbox is bounded and in memory. Only temporary failures are deferred;
  authentication, permission, validation, and unknown conflicts are rejected.
  Replay is manual, bounded, and has no background retry timer. Pending facts are
  lost when the process exits.
- Defaults: 5-second HTTP timeout, 8 recalled facts, 16 extracted facts of at most
  4,000 characters each, 16,000 context characters, and 1,000 queued writes.
  Timeouts apply per HTTP operation, not to the whole turn.
- Rules are formatted ahead of facts. This does not guarantee model compliance,
  prompt-injection resistance, or safe retention of arbitrary user content.
- Use one Python Rail/store per worker. The outbox protects its queue operations;
  the complete Rail telemetry and tenant-discovery lifecycle are not advertised as
  thread-safe. See [reliability](docs/reliability.md).

## Develop

See [CONTRIBUTING.md](CONTRIBUTING.md) for tests, package builds, and contract checks.
The shared [contract fixtures](contracts/README.md) document the REST shapes used
by both packages. They do not substitute for tests against a deployed Caura release.

Licensed under [Apache-2.0](LICENSE).
