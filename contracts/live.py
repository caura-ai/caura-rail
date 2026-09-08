"""Verify both installed clients against a real Caura backend.

Requires CAURA_URL and CAURA_API_KEY (and CAURA_TENANT unless the backend
supports identity discovery). Creates and deletes two governance rules and
writes a few uniquely marked memories in fleet "rail-live".
"""

import os
import subprocess
import uuid
from pathlib import Path

import httpx
from caura_rail import MemoryScope, Rail, RestMemoryStore, StoreError, Visibility

FLEET = "rail-live"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit("FAILED: " + message)


def main() -> None:
    run_id = uuid.uuid4().hex[:8]
    marker = f"Rail live check {run_id}"
    scope = MemoryScope(
        agent_id=f"rail-live-py-{run_id}", fleet_id=FLEET, visibility=Visibility.TEAM
    )
    with RestMemoryStore.from_env() as store:
        rail = Rail(store, scope)

        # 1. Identity discovery or configured tenant, then a clean recall.
        ctx = rail.recall("What do we know?")
        check(not ctx.degraded, f"initial recall degraded: {ctx.errors}")
        tenant = store._resolve(scope)
        print("tenant:", tenant)

        # 2. Governance rules land in the context, heaviest first.
        admin = httpx.Client(
            base_url=store.base_url,
            headers={
                "X-API-Key": os.environ.get("CAURA_API_KEY", "standalone"),
                "X-Tenant-ID": tenant,
            },
            timeout=10,
        )
        rules = [
            (f"rail-live-{run_id}-low", "low"),
            (f"rail-live-{run_id}-high", "high"),
        ]
        try:
            for doc_id, weight in rules:
                response = admin.post(
                    "/api/v1/keystones",
                    json={
                        "tenant_id": tenant,
                        "fleet_id": FLEET,
                        "doc_id": doc_id,
                        "title": f"Rule {weight} {run_id}",
                        "content": f"Live check rule with {weight} weight.",
                        "scope": "fleet",
                        "weight": weight,
                    },
                )
                check(
                    response.is_success,
                    f"keystone set failed: HTTP {response.status_code}",
                )
            ctx = rail.recall("What are the rules?")
            check(not ctx.degraded, f"recall with rules degraded: {ctx.errors}")
            titles = [r.title for r in ctx.keystones if run_id in r.title]
            check(
                titles == [f"Rule high {run_id}", f"Rule low {run_id}"],
                f"rule order: {titles}",
            )
            check(
                ctx.text.startswith("### GOVERNANCE RULES"),
                "rules must lead the context text",
            )

            # 3. A turn writes the extracted fact, and a repeat is deduplicated.
            with rail.turn("Remember: " + marker) as turn:
                turn.reply = "Noted"
            check(not turn.degraded, f"turn degraded: {turn.errors} {turn.writes}")
            check(turn.writes[0].status == "written", f"first write: {turn.writes}")
            again = store.write(marker, scope)
            check(again.status == "deduplicated", f"repeat write: {again}")
            check(
                again.id == turn.writes[0].id,
                "duplicate must point at the existing memory",
            )

            # 4. Another agent in the fleet recalls it.
            reader = Rail(store, scope.for_agent(f"rail-live-reader-{run_id}"))
            ctx = reader.recall(marker)
            check(
                any(marker in f.content for f in ctx.facts),
                "fleet peer could not recall the fact",
            )

            # 5. Backend validation failures are rejected, not deferred.
            try:
                store.write("tiny", scope)
            except StoreError as exc:
                check(
                    not exc.retryable and exc.status == 422,
                    f"short content: {exc} {exc.status}",
                )
            else:
                raise SystemExit("FAILED: backend accepted content below its minimum length")
            with rail.turn("Remember: tiny") as turn:
                turn.reply = "Noted"
            check(
                turn.writes[0].status == "rejected",
                f"short fact via turn: {turn.writes}",
            )
            check(
                rail.outbox.total_dropped == 0 and len(rail.outbox) == 0,
                "nothing should be queued",
            )

            # 6. The TypeScript client reads what Python wrote and writes its own fact.
            subprocess.run(
                [
                    "node",
                    str(Path(__file__).with_name("live_peer.mjs")),
                    marker,
                    scope.agent_id.replace("-py-", "-ts-"),
                ],
                check=True,
                timeout=60,
                env={**os.environ, "CAURA_TENANT": tenant},
            )
            ctx = reader.recall(f"TypeScript live check {run_id}")
            check(
                any(f.content == f"TypeScript live check {run_id} recorded." for f in ctx.facts),
                "Python could not recall the fact written by TypeScript",
            )
        finally:
            for doc_id, _ in rules:
                admin.delete(
                    f"/api/v1/keystones/{doc_id}",
                    params={"tenant_id": tenant, "fleet_id": FLEET},
                )
            admin.close()
    print("Live verification passed against", store.base_url)


if __name__ == "__main__":
    main()
