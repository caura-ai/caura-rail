# Caura Rail for Python

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

Full documentation, including the guide, API reference, and reliability
semantics, lives in the
[repository](https://github.com/caura-ai/caura-rail-next#readme).
A TypeScript package with the same semantics is published as `@caura/rail`.

Licensed under Apache-2.0.
