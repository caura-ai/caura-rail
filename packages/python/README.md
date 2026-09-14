# Caura Rail for Python

[![PyPI](https://img.shields.io/pypi/v/caura-rail?label=PyPI&color=0E6B5A)](https://pypi.org/project/caura-rail/) [![Python](https://img.shields.io/pypi/pyversions/caura-rail?label=Python)](https://pypi.org/project/caura-rail/) [![CI](https://img.shields.io/github/actions/workflow/status/caura-ai/caura-rail/ci.yml?label=CI)](https://github.com/caura-ai/caura-rail/actions/workflows/ci.yml) [![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/caura-ai/caura-rail/blob/main/LICENSE)

Memory operations around agent turns: fetch governance rules and relevant facts
from [Caura](https://caura.ai) before your agent runs, then extract and store
facts from the completed turn. Fully typed, synchronous and asynchronous.

```bash
python -m pip install caura-rail
```

```python
from caura_rail import MemoryScope, Rail, RestMemoryStore

with RestMemoryStore.from_env() as store:  # CAURA_URL, CAURA_API_KEY
    rail = Rail(store, MemoryScope(agent_id="support-1"))
    with rail.turn("Remember: We deploy in eu-west-1.") as turn:
        turn.reply = "Noted. " + turn.context.text  # pass context to your model
    print(turn.reply, [w.status for w in turn.writes])
```

Prefer the thin `caura-client` package when you only need to call the API; Rail
adds the turn lifecycle, governance ordering, extraction, and replay on top.

Full documentation, including the guide, API reference, and reliability
semantics, lives in the
[repository](https://github.com/caura-ai/caura-rail#readme).
A TypeScript package with the same semantics is published as `@caura/rail`.

Licensed under Apache-2.0.
