"""Harborline support desk — FastAPI orchestrator."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import governance, specialist
from .config import Settings, load_settings

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="Harborline Rail Demo", version="1.0.0")
settings: Settings = load_settings()

SESSION: dict[str, Any] = {
    "fleetId": None,
    "tenantId": None,
    "marker": None,
    "keystoneDocId": None,
    "intakeAgentId": None,
    "specialistAgentId": None,
    "turns": [],
}


class BootstrapRequest(BaseModel):
    runId: str | None = None


class TurnRequest(BaseModel):
    message: str = Field(min_length=1)
    agent: str = Field(pattern="^(intake|specialist)$")


class RecallRequest(BaseModel):
    query: str = Field(min_length=1)


def _require_session() -> dict[str, Any]:
    if not SESSION.get("fleetId"):
        raise HTTPException(status_code=400, detail="Call /api/bootstrap first")
    return SESSION


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "backend": settings.backend,
        "cauraUrl": settings.caura_url,
        "llmMode": "openai" if settings.openai_api_key else "deterministic",
        "fleetId": SESSION.get("fleetId"),
    }


@app.get("/api/session")
async def get_session() -> dict[str, Any]:
    return {
        "backend": settings.backend,
        "fleetId": SESSION.get("fleetId"),
        "tenantId": SESSION.get("tenantId"),
        "marker": SESSION.get("marker"),
        "keystoneDocId": SESSION.get("keystoneDocId"),
        "intakeAgentId": SESSION.get("intakeAgentId"),
        "specialistAgentId": SESSION.get("specialistAgentId"),
        "turns": SESSION.get("turns", []),
        "llmMode": "openai" if settings.openai_api_key else "deterministic",
    }


@app.post("/api/bootstrap")
async def bootstrap(body: BootstrapRequest | None = None) -> dict[str, Any]:
    run_id = (body.runId if body and body.runId else uuid.uuid4().hex[:10]).lower()
    # Agent ids are unique per run: Caura binds an agent to the fleet of its first write.
    fleet_id = f"demo-{run_id}-harborline"
    intake_agent = f"intake-{run_id}"
    specialist_agent = f"specialist-{run_id}"
    marker = f"hl-{run_id}"
    doc_id = f"demo-pii-{run_id}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        tenant_id = await governance.discover_tenant(settings, client)

        if settings.backend == "oss":
            seed = await client.post(
                f"{settings.caura_url}/api/v1/memories",
                headers={
                    "X-API-Key": settings.caura_api_key,
                    "X-Tenant-ID": tenant_id,
                    "Content-Type": "application/json",
                },
                json={
                    "tenant_id": tenant_id,
                    "agent_id": intake_agent,
                    "fleet_id": fleet_id,
                    "content": (f"Harborline demo bootstrap marker {marker} for fleet {fleet_id}."),
                    "visibility": "scope_team",
                    "write_mode": "strong",
                },
            )
            if seed.status_code >= 400 and seed.status_code != 409:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"bootstrap seed write failed: HTTP {seed.status_code} {seed.text[:300]}"
                    ),
                )

        rule_content = (
            "Never paste raw card numbers, CVVs, or bank account numbers into tickets "
            f"or chat. Redact PANs to last-4 only. Demo marker {marker}."
        )
        try:
            await governance.upsert_fleet_keystone(
                settings,
                client,
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                doc_id=doc_id,
                title="PII handling",
                content=rule_content,
                author_agent_id=intake_agent,
            )
        except governance.GovernanceError as error:
            # Configuration problems (for example a missing rule-author key on
            # managed Caura) are the caller's to fix; say so instead of a 500.
            raise HTTPException(status_code=400, detail=str(error)) from error

    SESSION.update(
        {
            "fleetId": fleet_id,
            "tenantId": tenant_id,
            "marker": marker,
            "keystoneDocId": doc_id,
            "intakeAgentId": intake_agent,
            "specialistAgentId": specialist_agent,
            "turns": [],
        }
    )
    return {
        "fleetId": fleet_id,
        "tenantId": tenant_id,
        "marker": marker,
        "keystoneDocId": doc_id,
        "intakeAgentId": intake_agent,
        "specialistAgentId": specialist_agent,
        "backend": settings.backend,
    }


@app.post("/api/turn")
async def turn(body: TurnRequest) -> dict[str, Any]:
    session = _require_session()
    fleet_id = session["fleetId"]

    if body.agent == "intake":
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(
                    f"{settings.intake_url}/turn",
                    json={
                        "fleetId": fleet_id,
                        "agentId": session["intakeAgentId"],
                        "message": body.message,
                    },
                )
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=502, detail=f"intake agent unreachable: {exc}"
                ) from exc
        if resp.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"intake agent error: HTTP {resp.status_code} {resp.text[:400]}",
            )
        payload = resp.json()
    else:
        try:
            payload = await specialist.run_specialist_turn(
                fleet_id,
                body.message,
                agent_id=session["specialistAgentId"],
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    SESSION.setdefault("turns", []).append(payload)
    return payload


@app.post("/api/recall")
async def recall(body: RecallRequest) -> dict[str, Any]:
    session = _require_session()
    try:
        return await specialist.recall_only(
            session["fleetId"],
            body.query,
            agent_id=session["specialistAgentId"],
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/cleanup")
async def cleanup() -> dict[str, Any]:
    fleet_id = SESSION.get("fleetId")
    tenant_id = SESSION.get("tenantId")
    doc_id = SESSION.get("keystoneDocId")
    removed = False
    if fleet_id and tenant_id and doc_id:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await governance.delete_fleet_keystone(
                settings,
                client,
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                doc_id=doc_id,
            )
            removed = True
    SESSION.update(
        {
            "fleetId": None,
            "tenantId": None,
            "marker": None,
            "keystoneDocId": None,
            "intakeAgentId": None,
            "specialistAgentId": None,
            "turns": [],
        }
    )
    return {"removedKeystone": removed}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
