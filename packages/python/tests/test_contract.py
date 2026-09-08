import copy
import json
from pathlib import Path

import httpx
import pytest

from caura_rail import (
    AsyncRail,
    AsyncRestMemoryStore,
    MemoryScope,
    Rail,
    RestMemoryStore,
    StoreError,
    Visibility,
)

CONTRACT = json.loads((Path(__file__).parents[3] / "contracts/caura.json").read_text())
SCOPE = MemoryScope(agent_id="support-1", fleet_id="support", visibility=Visibility.TEAM)


class Backend:
    def __init__(self):
        self.calls = []
        self.written = False

    def __call__(self, request):
        self.calls.append(request)
        assert request.headers["X-API-Key"] == "test-key"
        if request.url.path == "/api/v1/whoami":
            return httpx.Response(200, json=CONTRACT["identity"])
        assert request.headers["X-Tenant-ID"] == CONTRACT["tenant"]
        if request.url.path == "/api/v1/keystones":
            assert dict(request.url.params) == {
                "tenant_id": CONTRACT["tenant"],
                "agent_id": "support-1",
                "fleet_id": "support",
            }
            return httpx.Response(200, json=CONTRACT["keystones_response"])
        if request.url.path == "/api/v1/search":
            assert json.loads(request.content) == CONTRACT["search_request"]
            return httpx.Response(200, json=CONTRACT["search_response"])
        if request.url.path == "/api/v1/memories":
            assert json.loads(request.content) == CONTRACT["write_request"]
            key = "duplicate_response" if self.written else "write_response"
            status = 409 if self.written else 201
            self.written = True
            return httpx.Response(status, json=CONTRACT[key])
        raise AssertionError("Unexpected endpoint: " + str(request.url))


def test_sync_contract_and_discovery():
    backend = Backend()
    with httpx.Client(transport=httpx.MockTransport(backend)) as client:
        with RestMemoryStore(api_key="test-key", client=client) as store:
            rail = Rail(store, SCOPE, extractor=lambda *_: [CONTRACT["fact"]])
            with rail.turn(CONTRACT["query"]) as turn:
                assert turn.context.text == CONTRACT["context_text"]
                assert not turn.degraded
                turn.reply = "Acknowledged"
            assert turn.writes[0].status == "written"
            assert store.write(CONTRACT["fact"], SCOPE).status == "deduplicated"
        assert not client.is_closed
    assert sum(r.url.path == "/api/v1/whoami" for r in backend.calls) == 1


async def test_async_contract_and_discovery():
    backend = Backend()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
        async with AsyncRestMemoryStore(api_key="test-key", client=client) as store:
            rail = AsyncRail(store, SCOPE, extractor=lambda *_: [CONTRACT["fact"]])
            async with rail.turn(CONTRACT["query"]) as turn:
                assert turn.context.text == CONTRACT["context_text"]
                turn.reply = "Acknowledged"
            assert turn.writes[0].status == "written"
            assert (await store.write(CONTRACT["fact"], SCOPE)).status == "deduplicated"
        assert not client.is_closed
    assert sum(r.url.path == "/api/v1/whoami" for r in backend.calls) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 422, 429, 503])
async def test_http_failures_are_classified(status):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(status, json={"detail": "private data"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        store = AsyncRestMemoryStore(tenant_id=CONTRACT["tenant"], client=client)
        with pytest.raises(StoreError) as error:
            await store.recall("query", SCOPE)
        assert error.value.status == status
        assert error.value.retryable == (status in (429, 503))
        assert "private data" not in str(error.value)


@pytest.mark.parametrize("payload", [{}, {"items": None}, {"items": [None]}, {"items": [{}]}])
async def test_malformed_search_is_not_empty_success(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        rail = AsyncRail(AsyncRestMemoryStore(tenant_id="tenant", client=client), SCOPE)
        ctx = await rail.recall("query")
        assert ctx.degraded


async def test_missing_identity_never_becomes_default_tenant():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"tenant_id": None})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = AsyncRestMemoryStore(client=client)
        with pytest.raises(StoreError):
            await store.write("fact", SCOPE)
    assert calls == ["/api/v1/whoami"]


async def test_explicit_tenant_and_mismatch():
    def handler(request):
        assert request.url.path == "/api/v1/search"
        assert json.loads(request.content)["tenant_id"] == "explicit"
        return httpx.Response(200, json={"items": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = AsyncRestMemoryStore(tenant_id="explicit", client=client)
        assert await store.recall("query", SCOPE) == []
        with pytest.raises(StoreError, match="does not match"):
            await store.recall("query", MemoryScope(agent_id="agent", tenant_id="other"))


async def test_generic_conflict_and_duplicate_race():
    data = copy.deepcopy(CONTRACT["duplicate_response"])
    data["error"]["details"] = {"reason": "winner_no_longer_live"}
    for body, retryable in [({"detail": "Conflict"}, False), (data, True)]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(409, json=body))
        ) as client:
            store = AsyncRestMemoryStore(tenant_id="tenant", client=client)
            with pytest.raises(StoreError) as error:
                await store.write("fact", SCOPE)
            assert error.value.retryable is retryable


async def test_keystone_envelope_and_truncation():
    for truncated in (False, True):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={"items": CONTRACT["keystones_response"]},
                    headers={"X-Truncated": str(truncated).lower()},
                )
            )
        ) as client:
            store = AsyncRestMemoryStore(tenant_id="tenant", client=client)
            if truncated:
                with pytest.raises(StoreError, match="truncated"):
                    await store.keystones(SCOPE)
            else:
                assert (await store.keystones(SCOPE))[0].weight == 100


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("CAURA_URL", "https://example.invalid")
    monkeypatch.setenv("CAURA_TENANT", "environment")
    with RestMemoryStore.from_env(tenant_id="override") as store:
        assert store.base_url == "https://example.invalid"
        assert store._tenant(SCOPE) == "override"


async def test_search_limits_match_the_server():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"items": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = AsyncRestMemoryStore(tenant_id="tenant", client=client)
        await store.recall("q" * 6000, SCOPE, top_k=20)
        assert len(seen[0]["query"]) == 5000 and seen[0]["top_k"] == 20
        with pytest.raises(ValueError, match="1 to 20"):
            await store.recall("query", SCOPE, top_k=21)
    assert len(seen) == 1
