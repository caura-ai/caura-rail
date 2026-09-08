"""Verify both installed clients over HTTP, using the local contract fixture."""

import subprocess
from pathlib import Path

from caura_rail import MemoryScope, Rail, RestMemoryStore, Visibility
from fixture import API_KEY, serve


def main() -> None:
    scope = MemoryScope(agent_id="python-agent", fleet_id="support", visibility=Visibility.TEAM)
    with (
        serve() as (url, state),
        RestMemoryStore(base_url=url, api_key=API_KEY) as store,
    ):
        rail = Rail(store, scope)
        with rail.turn("Remember: Python learned the deployment region.") as turn:
            if turn.degraded:
                raise SystemExit("Contract recall degraded: " + "; ".join(turn.context.errors))
            turn.reply = "Recorded"
        assert turn.writes[0].status == "written", turn.writes
        assert store.write("Python learned the deployment region.", scope).status == "deduplicated"
        subprocess.run(
            ["node", str(Path(__file__).with_name("peer.mjs")), url],
            check=True,
            timeout=30,
        )
        ctx = rail.recall("What did TypeScript learn?")
        assert not ctx.degraded, ctx.errors
        assert any(f.content == "TypeScript learned the renewal date." for f in ctx.facts)
        assert len(ctx.keystones) == 2
        assert ("GET", "/api/v1/whoami") in state.requests
    print("Python -> HTTP -> TypeScript -> HTTP -> Python contract round trip passed.")


if __name__ == "__main__":
    main()
