"""Write and recall a fact against a configured Caura backend."""

import uuid

from caura_rail import MemoryScope, Rail, RestMemoryStore, Visibility

marker = "Rail example " + str(uuid.uuid4())
scope = MemoryScope(agent_id="rail-example-writer", fleet_id="rail-examples", visibility=Visibility.TEAM)

with RestMemoryStore.from_env() as store:
    writer = Rail(store, scope)
    with writer.turn("Remember: " + marker) as turn:
        turn.reply = "Noted"
    if turn.degraded or not turn.writes or turn.writes[0].status != "written":
        raise RuntimeError("Write did not complete; inspect the turn errors and backend configuration")
    reader = Rail(store, scope.for_agent("rail-example-reader"))
    ctx = reader.recall(marker)
    if ctx.degraded or not any(marker in fact.content for fact in ctx.facts):
        raise RuntimeError("Second agent could not recall the fact; check fleet permissions")
    print("Second agent recalled the saved fact:", marker)
