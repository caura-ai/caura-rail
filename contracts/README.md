# Contract verification

Both packages are verified at three levels. Unit tests cover behavior with
in-process stores. Contract tests exercise the real HTTP client code against a
fixture that mirrors the Caura REST API. Live tests run against a real Caura
server. All three run in CI on every push.

## Shared fixture data

`caura.json` holds synthetic request and response examples used by the Python
tests, the Node tests, and the fixture server: the identity response from
`GET /api/v1/whoami`, a `SearchRequest` with `caller_agent_id` and `fleet_ids`,
a `KeystoneDoc` list with rule fields inside `data`, a `MemoryOut` write
response, and a `DUPLICATE_MEMORY` error envelope. The schema references are the
Caura server's `SearchRequest`, `SearchResponse`, `KeystoneDoc`, `MemoryCreate`,
`MemoryOut`, and `duplicate_memory` definitions in
[caura-ai/caura](https://github.com/caura-ai/caura).

## Fixture server

`fixture.py` runs a loopback HTTP server implementing the four endpoints Rail
uses, with the server's status codes, field names, limits, and error shapes:

- `GET /api/v1/whoami` returns the fixture identity.
- `GET /api/v1/keystones` returns a bare array of rules for the fixture tenant.
- `POST /api/v1/search` requires `caller_agent_id`, accepts `top_k` 1 to 20 and
  queries up to 5,000 characters, and returns `{"items": [...]}` of stored
  memories that share a word with the query, filtered by agent, fleet, and
  visibility.
- `POST /api/v1/memories` requires 10 to 10,000 characters of content and a valid
  visibility, answers `201` with the stored record, and `409 DUPLICATE_MEMORY`
  for repeated content.

It does not implement authentication beyond a fixed key, semantic retrieval, or
persistence. Run it standalone with `python contracts/fixture.py`.

## Programs

| Program | What it checks | Needs |
|---|---|---|
| `smoke.py` | Python writes through the fixture, TypeScript (`peer.mjs`) recalls it and writes, Python recalls that. Discovery, rules, dedup. | Both packages installed, Node. |
| `verify_docs.py` | Every `python` and `ts` code block in `README.md` and `docs/*.md` runs against a fresh fixture and type-checks with mypy and tsc. | Both packages, mypy, typescript, `@types/node`. |
| `live.py` | Identity discovery, rule ordering, write, exact-duplicate detection, fleet-peer recall, validation rejection, and a TypeScript peer (`live_peer.mjs`) round trip against a real server. Creates and deletes two rules in fleet `rail-live`. | `CAURA_URL`, `CAURA_API_KEY`, optional `CAURA_TENANT`. |

From the repository root after installing both packages:

```bash
python contracts/smoke.py
python contracts/verify_docs.py
CAURA_URL=http://localhost:8000 CAURA_API_KEY=standalone python contracts/live.py
```

CI runs `live.py` against the open-source Caura release pinned in
`.github/workflows/ci.yml`, brought up with the server's own Docker Compose file.
