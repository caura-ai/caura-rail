# Caura — governed shared memory for AI agent fleets

Caura (formerly MemClaw) is an Agent DB — governed shared memory for AI agent fleets. Agents commit what they learn once; every agent in the fleet recalls it through MCP tools, REST, or Caura Rail (preview), subject to tenant isolation, visibility scope (scope_agent / scope_team / scope_org) and caller trust level.

**Caura Rail (preview)** is the deterministic way to use that memory from Python.
Rail runs recall before every agent turn and commit after it, in your code
rather than at the model's discretion, so the model cannot skip the memory
step. What Rail guarantees is the invocation: a failed recall or write degrades
the turn and is reported, but the turn still runs (fail-open) unless you require
governance rules. Rail does not guarantee persistence; deferred writes wait in
an in-process outbox until you flush it. See
[Reliability](https://github.com/caura-ai/caura-rail/blob/main/docs/reliability.md).

[![PyPI](https://img.shields.io/pypi/v/caura-rail?label=PyPI&color=0E6B5A)](https://pypi.org/project/caura-rail/) [![Python](https://img.shields.io/pypi/pyversions/caura-rail?label=Python)](https://pypi.org/project/caura-rail/) [![CI](https://img.shields.io/github/actions/workflow/status/caura-ai/caura-rail/ci.yml?label=CI)](https://github.com/caura-ai/caura-rail/actions/workflows/ci.yml) [![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/caura-ai/caura-rail/blob/main/LICENSE)

## Install

```bash
python -m pip install caura-rail
```

## Quickstart

Set `CAURA_URL` and `CAURA_API_KEY` for a managed workspace on
[caura.ai](https://caura.ai) or a self-hosted
[open-source server](https://github.com/caura-ai/caura), then wrap each agent
turn:

```python
from caura_rail import MemoryScope, Rail, RestMemoryStore

with RestMemoryStore.from_env() as store:  # CAURA_URL, CAURA_API_KEY
    rail = Rail(store, MemoryScope(agent_id="support-1"))
    with rail.turn("Remember: We deploy in eu-west-1.") as turn:
        turn.reply = "Noted. " + turn.context.text  # pass context to your model
    print(turn.reply, [w.status for w in turn.writes])
```

Before the agent runs, `turn.context` holds the governance rules and the facts
relevant to the message. After the block, Rail extracts the facts worth keeping
from the reply and writes them back. Fully typed, synchronous and asynchronous.

## Links

- Guide: https://github.com/caura-ai/caura-rail/blob/main/docs/guide.md
- API reference: https://github.com/caura-ai/caura-rail/blob/main/docs/api.md
- Caura documentation: https://caura.ai/docs
- Source: https://github.com/caura-ai/caura-rail (Apache-2.0)
- Issues: https://github.com/caura-ai/caura-rail/issues
- Changelog: https://github.com/caura-ai/caura-rail/blob/main/CHANGELOG.md
- Benchmark: https://github.com/caura-ai/caura-longmemeval (LongMemEval harness)
- TypeScript package with the same semantics: [`@caura/rail`](https://www.npmjs.com/package/@caura/rail)
- Direct REST client without the turn wrapper: [`caura-client`](https://pypi.org/project/caura-client/)

Licensed under Apache-2.0.
