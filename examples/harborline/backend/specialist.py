"""Harborline specialist agent — Python AsyncRail with required keystones."""

from __future__ import annotations

from typing import Any

from caura_rail import AsyncRail, AsyncRestMemoryStore, MemoryScope, Visibility

from .llm import compose_reply


def decisions_only(message: str, _reply: str) -> list[str]:
    """Specialist stores only explicit Decision: lines (recall-heavy otherwise)."""
    facts: list[str] = []
    for line in message.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("decision:"):
            text = stripped if len(stripped) >= 10 else ""
            if text:
                facts.append(text)
    return facts


def serialize_turn(
    *,
    agent_id: str,
    fleet_id: str,
    message: str,
    turn: Any,
    llm_mode: str,
    rail: AsyncRail,
) -> dict[str, Any]:
    return {
        "agentId": agent_id,
        "fleetId": fleet_id,
        "message": message,
        "reply": turn.reply,
        "llmMode": llm_mode,
        "degraded": turn.degraded,
        "errors": list(turn.errors),
        "context": {
            "text": turn.context.text,
            "degraded": turn.context.degraded,
            "errors": list(turn.context.errors),
            "keystones": [
                {
                    "docId": k.doc_id,
                    "title": k.title,
                    "content": k.content,
                    "weight": k.weight,
                }
                for k in turn.context.keystones
            ],
            "facts": [
                {"id": f.id, "content": f.content, "agentId": f.agent_id}
                for f in turn.context.facts
            ],
        },
        "writes": [{"status": w.status, "id": w.id, "error": w.error} for w in turn.writes],
        "telemetry": {
            "turnsTotal": rail.telemetry.turns_total,
            "degradedTurns": rail.telemetry.degraded_turns,
            "writesDeferred": rail.telemetry.writes_deferred,
            "writesRejected": rail.telemetry.writes_rejected,
            "extractionFailures": rail.telemetry.extraction_failures,
        },
    }


async def run_specialist_turn(fleet_id: str, message: str, *, agent_id: str) -> dict[str, Any]:
    if not fleet_id.startswith("demo-"):
        raise ValueError("fleetId must start with demo-")

    async with AsyncRestMemoryStore.from_env(timeout=30.0) as store:
        scope = MemoryScope(
            agent_id=agent_id,
            fleet_id=fleet_id,
            visibility=Visibility.TEAM,
        )
        rail = AsyncRail(
            store,
            scope,
            extractor=decisions_only,
            top_k=12,
            require_keystones=True,
        )
        async with rail.turn(message) as turn:
            reply, mode = compose_reply("specialist", message, turn.context.text)
            turn.reply = reply

        if any(w.status == "deferred" for w in turn.writes):
            await rail.flush_outbox(max_attempts=2)

        return serialize_turn(
            agent_id=agent_id,
            fleet_id=fleet_id,
            message=message,
            turn=turn,
            llm_mode=mode,
            rail=rail,
        )


async def recall_only(fleet_id: str, query: str, *, agent_id: str) -> dict[str, Any]:
    """Expose Rail.recall without incrementing turn write counters."""
    async with AsyncRestMemoryStore.from_env(timeout=30.0) as store:
        scope = MemoryScope(
            agent_id=agent_id,
            fleet_id=fleet_id,
            visibility=Visibility.TEAM,
        )
        rail = AsyncRail(store, scope, require_keystones=True, top_k=12)
        context = await rail.recall(query)
        return {
            "agentId": agent_id,
            "fleetId": fleet_id,
            "query": query,
            "text": context.text,
            "degraded": context.degraded,
            "errors": list(context.errors),
            "keystones": [
                {
                    "docId": k.doc_id,
                    "title": k.title,
                    "content": k.content,
                    "weight": k.weight,
                }
                for k in context.keystones
            ],
            "facts": [
                {"id": f.id, "content": f.content, "agentId": f.agent_id} for f in context.facts
            ],
        }
