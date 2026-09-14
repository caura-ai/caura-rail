# Changelog

All notable changes to `caura-rail` (PyPI) and `@caura/rail` (npm). Both
packages share version numbers and release together.

## Unreleased

## 1.0.1 - 2026-09-14

No behaviour changes to the libraries.

- Documented the minimum open-source server release, backend-v2.47.0, in which
  search honours the caller identity Rail asserts so agents recall their own
  private facts, and the `CAURA_VERSION` pin for self-hosted servers.
- Documented the fleet-scope policy (an agent belongs to the fleet of its first
  write), semantic deduplication, rule authoring on multi-tenant Caura, and the
  gateway warm-up on first identity resolution.
- README restyled; package READMEs gain badges and drop the client comparison.
- Live CI job runs the pinned server release instead of the `latest` image and
  verifies the running version. The docs harness runs JavaScript blocks and has
  a `--live` mode against a real backend.
- Repository governance: protected `main`, DCO and CodeQL workflows, dependency
  audit, Dependabot, PR and issue templates.

## 1.0.0 - 2026-09-08

First stable release.

- Python `Rail`, `AsyncRail`, `RestMemoryStore`, `AsyncRestMemoryStore`,
  `MemoryScope`, `Outbox`, `Telemetry`, and result types; TypeScript `Rail`,
  `RestMemoryStore`, `MemoryScope`, `Outbox`, and result types.
- Turn lifecycle: recall rules and facts, run the application's agent, extract,
  write; nothing is written when the agent fails.
- Governance rules ordered by weight ahead of facts, with optional
  `require_keystones` / `requireKeystones` enforcement and truncation detection.
- Write classification into written, deduplicated, deferred, and rejected, with a
  bounded in-memory outbox and explicit replay.
- Tenant discovery from `GET /api/v1/whoami` when no tenant is configured.
- Server limits applied client-side: `top_k` 1 to 20 and 5,000-character search
  queries.
- Default HTTP timeout of 15 seconds per request, measured against writes with
  server-side enrichment and first requests through the Caura gateway.
- Python package is fully typed (`py.typed`, strict mypy) and exports
  `MemoryStore` / `AsyncMemoryStore` protocols, `Turn` / `AsyncTurn`, and callable
  aliases. TypeScript ships declarations.
- Verified against the open-source Caura server release backend-v2.47.5, on
  Python 3.10 to 3.14 and Node.js 22 and 24. Documentation code blocks are
  executed and type-checked in CI.
