# Harborline — Caura Rail demo

A small support-desk demo where two assistants share memory through
[Caura Rail](https://caura.ai/docs/integrations/rail/). The same code runs
against self-hosted Caura (`CAURA_BACKEND=oss`) and managed Caura
(`CAURA_BACKEND=saas`).

## Scenario

**Harborline** is a fictional B2B payments company. When a merchant calls in:

1. **Intake** (TypeScript, `@caura/rail`) captures durable notes — default
   `Remember:` / `We use` / … lines plus support-script `Customer note:` lines —
   into a team-scoped fleet.
2. **Specialist** (Python, `AsyncRail`) escalates with `require_keystones=True`,
   so fleet policy (PII handling) leads every prompt. It only stores explicit
   `Decision:` lines.
3. The web UI shows, for each turn, the Rail context (rules then facts), the
   reply, and every write status (`written`, `deduplicated`, `rejected`, …).

Each run creates a unique fleet `demo-<id>-harborline` and agent ids
`intake-<id>` / `specialist-<id>` (Caura binds an agent to the fleet of its first
write). Governance rules created for the demo are deleted on cleanup.

## Architecture

```
Browser  →  FastAPI orchestrator (Python)
               ├─ specialist turns via caura-rail AsyncRail
               ├─ keystone bootstrap / cleanup (REST)
               └─ HTTP → intake service (Node / @caura/rail)
```

| Piece | Role |
|---|---|
| `backend/` | FastAPI app, specialist agent, governance helpers, LLM/deterministic replies |
| `intake/` | TypeScript HTTP microservice wrapping Rail for first-line turns |
| `frontend/` | Static UI served by FastAPI (`/`, `/static/*`) |
| `scripts/run_scenario.py` | Scripted assertions used by `./demo.sh` |
| `secrets/` | Local connection files — **not committed** |

Assistants call OpenAI when `OPENAI_API_KEY` is available (`secrets/llm.env`).
Without it — or with `DEMO_FORCE_DETERMINISTIC=1` — they answer from a
deterministic template that still surfaces the Rail context.

## Prerequisites

- Python 3.10+, Node.js 22+, npm
- A reachable Caura deployment: the open-source server (see the
  [self-hosting guide](https://caura.ai/docs/getting-started/self-host)) or a
  caura.ai tenant
- Connection files under `secrets/`, created from the templates:

```bash
cp secrets/oss.env.example secrets/oss.env      # edit CAURA_URL / CAURA_API_KEY
cp secrets/saas.env.example secrets/saas.env    # tenant key plus the rule-author key, see below
cp secrets/llm.env.example secrets/llm.env      # optional; omit for deterministic replies
```

`secrets/*.env` files are ignored by git.

## How to run

```bash
# Self-hosted open-source Caura
CAURA_BACKEND=oss ./demo.sh

# Managed Caura
CAURA_BACKEND=saas ./demo.sh

# Force offline model replies even if llm.env has a key
DEMO_FORCE_DETERMINISTIC=1 CAURA_BACKEND=oss ./demo.sh
```

`./demo.sh` creates a venv, installs pinned dependencies, starts intake + API,
runs unit tests, executes the scripted scenario, and exits non-zero on failure.

### Interactive UI

After dependencies are installed once:

```bash
export CAURA_BACKEND=oss   # or saas
set -a; source secrets/${CAURA_BACKEND}.env
[[ -f secrets/llm.env ]] && source secrets/llm.env
set +a

# terminal 1
(cd intake && npm start)

# terminal 2
source .venv/bin/activate
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8080
```

Open http://127.0.0.1:8080 — **Start new fleet**, send turns as intake or
specialist, then **Cleanup keystone**.

### Rule authoring on managed Caura

Managed Caura refuses a tenant-scoped key for keystone writes (HTTP 403
`AGENT_NOT_REGISTERED`), so `CAURA_BACKEND=saas` needs an agent-scoped
rule-author credential. Mint one with your tenant key, once, and put the
`raw_key` and agent id into `secrets/saas.env`:

```bash
curl -X POST "https://caura.ai/api/v1/admin/agent-keys/provision" \
  -H "X-API-Key: $CAURA_API_KEY" -H "Content-Type: application/json" \
  -d '{"agent_id": "harborline-rule-author", "label": "harborline demo", "initial_trust": 2}'
# secrets/saas.env
# CAURA_RULE_AUTHOR_KEY=mc_...        (the raw_key, shown only once)
# CAURA_RULE_AUTHOR_AGENT=harborline-rule-author
```

Without it, **Start new fleet** fails with HTTP 400 and this instruction. See
[Per-agent keys](https://caura.ai/docs/integrations/per-agent-keys/).

### Switch backends

Only `CAURA_BACKEND` changes. The app loads `secrets/oss.env` or
`secrets/saas.env` at startup; no code changes.

| Variable | OSS | SaaS |
|---|---|---|
| `CAURA_URL` | local server | `https://caura.ai` |
| `CAURA_API_KEY` | often `standalone` | tenant `mc_` key |
| `CAURA_RULE_AUTHOR_KEY` / `_AGENT` | unused (trust promotion) | required, see above |

## What the demo shows

The scripted scenario checks:

1. Fleet + PII keystone bootstrap  
2. Intake stores two facts (`Remember:` + `Customer note:`)  
3. Specialist sees governance rules and teammate facts  
4. Re-writing the same fact returns `deduplicated`  
5. Specialist `Decision:` write succeeds  
6. Overs short fact (`Remember: xx`) returns `rejected` (HTTP 422)  
7. `recall()` without a turn still returns rules + facts  
8. Keystone cleanup  

## Provenance

This application was written by a coding agent that started only from the
public Caura documentation, as a test of that documentation, and then reviewed
and verified by the Rail maintainers against the open-source server and caura.ai.
It is kept as an example of a complete Rail application, not as a reference for
production hardening.

## License

Apache-2.0, like the rest of this repository.
