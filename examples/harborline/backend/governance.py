"""Create and delete fleet keystones; OSS vs SaaS authoring differs."""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class GovernanceError(RuntimeError):
    pass


async def discover_tenant(settings: Settings, client: httpx.AsyncClient) -> str:
    if settings.caura_tenant:
        return settings.caura_tenant
    resp = await client.get(
        f"{settings.caura_url}/api/v1/whoami",
        headers={"X-API-Key": settings.caura_api_key},
    )
    if resp.status_code >= 400:
        raise GovernanceError(f"whoami failed: HTTP {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    tenant = data.get("tenant_id") or data.get("tenant") or data.get("default_tenant_id")
    if not tenant:
        # Standalone often embeds tenant under nested shapes; try common keys.
        for key in ("tenantId", "org_id"):
            if data.get(key):
                tenant = data[key]
                break
    if not tenant:
        raise GovernanceError(f"whoami did not return a tenant: {sorted(data.keys())}")
    return str(tenant)


async def ensure_writer_trust(
    settings: Settings,
    client: httpx.AsyncClient,
    *,
    tenant_id: str,
    agent_id: str,
) -> None:
    """On OSS standalone, promote the writer so it can author fleet keystones."""
    if settings.backend != "oss":
        return
    resp = await client.patch(
        f"{settings.caura_url}/api/v1/agents/{agent_id}/trust",
        params={"tenant_id": tenant_id},
        headers={
            "X-API-Key": settings.caura_api_key,
            "Content-Type": "application/json",
        },
        json={"trust_level": 2},
    )
    if resp.status_code >= 400:
        raise GovernanceError(
            f"trust promotion failed for {agent_id}: HTTP {resp.status_code} {resp.text[:300]}"
        )


async def upsert_fleet_keystone(
    settings: Settings,
    client: httpx.AsyncClient,
    *,
    tenant_id: str,
    fleet_id: str,
    doc_id: str,
    title: str,
    content: str,
    author_agent_id: str,
) -> dict[str, Any]:
    if settings.backend == "saas":
        # Managed Caura derives the acting identity from the credential and refuses
        # a tenant-scoped key for rule writes (HTTP 403 AGENT_NOT_REGISTERED), so an
        # agent-scoped rule-author credential is required. Mint one with the tenant
        # key, once, and put it in secrets/saas.env:
        #   curl -X POST "$CAURA_URL/api/v1/admin/agent-keys/provision" \
        #     -H "X-API-Key: $CAURA_API_KEY" -H "Content-Type: application/json" \
        #     -d '{"agent_id": "harborline-rule-author", "initial_trust": 2}'
        if not (settings.rule_author_key and settings.rule_author_agent):
            raise GovernanceError(
                "CAURA_BACKEND=saas needs CAURA_RULE_AUTHOR_KEY and CAURA_RULE_AUTHOR_AGENT in "
                "secrets/saas.env: managed Caura refuses a tenant-scoped key for rule writes. "
                "Mint an agent-scoped key at trust 2 with POST /api/v1/admin/agent-keys/provision "
                "(see https://caura.ai/docs/integrations/per-agent-keys/) and set both variables."
            )
        api_key = settings.rule_author_key
        agent_header = settings.rule_author_agent
    else:
        api_key = settings.caura_api_key
        agent_header = author_agent_id
        await ensure_writer_trust(settings, client, tenant_id=tenant_id, agent_id=author_agent_id)

    headers = {
        "X-API-Key": api_key,
        "X-Tenant-ID": tenant_id,
        "X-Agent-ID": agent_header,
        "Content-Type": "application/json",
    }
    body = {
        "tenant_id": tenant_id,
        "fleet_id": fleet_id,
        "doc_id": doc_id,
        "title": title,
        "content": content,
        "scope": "fleet",
        "weight": "high",
    }
    resp = await client.post(
        f"{settings.caura_url}/api/v1/keystones",
        headers=headers,
        json=body,
    )
    if resp.status_code >= 400:
        raise GovernanceError(f"keystone create failed: HTTP {resp.status_code} {resp.text[:400]}")
    return resp.json() if resp.content else {"doc_id": doc_id}


async def delete_fleet_keystone(
    settings: Settings,
    client: httpx.AsyncClient,
    *,
    tenant_id: str,
    fleet_id: str,
    doc_id: str,
) -> None:
    if settings.backend == "saas":
        api_key = settings.rule_author_key or settings.caura_api_key
    else:
        api_key = settings.caura_api_key
    resp = await client.delete(
        f"{settings.caura_url}/api/v1/keystones/{doc_id}",
        params={"tenant_id": tenant_id, "fleet_id": fleet_id},
        headers={
            "X-API-Key": api_key,
            "X-Tenant-ID": tenant_id,
        },
    )
    # 404 is fine during cleanup of a partially failed run.
    if resp.status_code >= 400 and resp.status_code != 404:
        raise GovernanceError(f"keystone delete failed: HTTP {resp.status_code} {resp.text[:300]}")
