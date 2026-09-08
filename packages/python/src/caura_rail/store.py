"""Synchronous and asynchronous clients for the Caura REST contract."""

import math
import os
from typing import Any, TypeVar
from urllib.parse import urlparse

import httpx

from .models import Fact, KeystoneRule, MemoryScope, StoreError, WriteResult

MAX_TOP_K = 20
"""Largest top_k the Caura search endpoint accepts."""

MAX_QUERY_CHARS = 5000
"""Longest query the Caura search endpoint accepts; longer queries are truncated."""

_ConfigT = TypeVar("_ConfigT", bound="_Config")
_SyncT = TypeVar("_SyncT", bound="RestMemoryStore")
_AsyncT = TypeVar("_AsyncT", bound="AsyncRestMemoryStore")


def _string(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StoreError("Invalid backend response: expected a nonempty string")
    return value


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StoreError("Invalid backend response: expected an object")
    return value


def _facts(data: Any) -> list[Fact]:
    items = _object(data).get("items")
    if not isinstance(items, list):
        raise StoreError("Invalid search response: missing items array")
    result = []
    for raw in items:
        row = _object(raw)
        agent = row.get("agent_id")
        if agent is not None:
            agent = _string(agent)
        result.append(Fact(_string(row.get("id")), _string(row.get("content")), agent))
    return result


def _keystones(data: Any) -> list[KeystoneRule]:
    items = data if isinstance(data, list) else _object(data).get("items")
    if not isinstance(items, list):
        raise StoreError("Invalid keystone response: expected an array")
    rules = []
    for raw in items:
        row = _object(raw)
        rule = _object(row.get("data"))
        weight = rule.get("weight")
        if type(weight) is not int:
            raise StoreError("Invalid keystone response: weight must be an integer")
        rules.append(
            KeystoneRule(
                _string(row.get("doc_id")),
                _string(rule.get("title")),
                _string(rule.get("content")),
                weight,
            )
        )
    return sorted(rules, key=lambda r: r.weight, reverse=True)


def _decode(response: httpx.Response, *, writing: bool = False) -> Any:
    if response.status_code == 409 and writing:
        # Generic conflicts must remain errors. Only the structured duplicate
        # code establishes deduplication without guessing from prose.
        try:
            error = response.json().get("error")
        except (ValueError, AttributeError):
            error = None
        if isinstance(error, dict) and error.get("code") == "DUPLICATE_MEMORY":
            details = _object(error.get("details"))
            if details.get("reason") == "winner_no_longer_live":
                raise StoreError("Duplicate winner no longer live", status=409, retryable=True)
            if details.get("reason") in ("exact_content_hash", "semantic_similarity"):
                return WriteResult("deduplicated", id=_string(details.get("existing_id")))
    if not response.is_success:
        code = response.status_code
        raise StoreError(
            f"Caura request failed (HTTP {code})",
            status=code,
            retryable=code in (408, 429) or 500 <= code < 600,
        )
    if response.headers.get("X-Truncated", "").lower() == "true":
        raise StoreError("Backend returned truncated governance rules")
    try:
        return response.json()
    except ValueError as exc:
        raise StoreError("Invalid backend response: expected JSON") from exc


def _written(data: Any) -> WriteResult:
    if isinstance(data, WriteResult):
        return data
    return WriteResult("written", id=_string(_object(data).get("id")))


class _Config:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str = "standalone",
        tenant_id: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("base_url must be an HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain credentials, query, or fragment")
        if not api_key.strip():
            raise ValueError("api_key must be nonempty")
        if tenant_id is not None and not tenant_id.strip():
            raise ValueError("tenant_id must be nonempty")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._tenant_id = tenant_id
        self.timeout = timeout

    @classmethod
    def from_env(cls: type[_ConfigT], **overrides: Any) -> _ConfigT:
        """Read CAURA_URL, CAURA_API_KEY, and CAURA_TENANT; keyword overrides win."""
        values: dict[str, Any] = {
            "base_url": os.environ.get("CAURA_URL", "http://localhost:8000"),
            "api_key": os.environ.get("CAURA_API_KEY", "standalone"),
            "tenant_id": os.environ.get("CAURA_TENANT") or None,
        }
        values.update(overrides)
        return cls(**values)

    def _tenant(self, scope: MemoryScope) -> str | None:
        if scope.tenant_id and self._tenant_id and scope.tenant_id != self._tenant_id:
            raise StoreError("Scope tenant does not match the store tenant")
        return scope.tenant_id or self._tenant_id

    def _request_options(
        self, path: str, tenant: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        headers = {"X-API-Key": self._api_key}
        if tenant:
            headers["X-Tenant-ID"] = tenant
        return {
            "url": self.base_url + path,
            "headers": headers,
            "timeout": self.timeout,
            "follow_redirects": False,
            **kwargs,
        }

    @staticmethod
    def _search(query: str, scope: MemoryScope, tenant: str, top_k: int) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be nonempty")
        if type(top_k) is not int or not 1 <= top_k <= MAX_TOP_K:
            raise ValueError(f"top_k must be an integer from 1 to {MAX_TOP_K}")
        body: dict[str, Any] = {
            "tenant_id": tenant,
            "query": query[:MAX_QUERY_CHARS],
            "caller_agent_id": scope.agent_id,
            "top_k": top_k,
        }
        if scope.fleet_id:
            body["fleet_ids"] = [scope.fleet_id]
        return body

    @staticmethod
    def _rule_params(scope: MemoryScope, tenant: str) -> dict[str, str]:
        params = {"tenant_id": tenant, "agent_id": scope.agent_id}
        if scope.fleet_id:
            params["fleet_id"] = scope.fleet_id
        return params

    @staticmethod
    def _write(fact: str, scope: MemoryScope, tenant: str) -> dict[str, Any]:
        if not isinstance(fact, str) or not fact.strip():
            raise ValueError("fact must be nonempty")
        body: dict[str, Any] = {
            "tenant_id": tenant,
            "agent_id": scope.agent_id,
            "content": fact,
            "visibility": scope.visibility.value,
            "write_mode": "strong",
        }
        if scope.fleet_id:
            body["fleet_id"] = scope.fleet_id
        return body


class RestMemoryStore(_Config):
    """Synchronous Caura REST client. Use as a context manager to close it."""

    def __init__(self, *args: Any, client: httpx.Client | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client()

    def _request(
        self,
        method: str,
        path: str,
        *,
        tenant: str | None = None,
        writing: bool = False,
        **kwargs: Any,
    ) -> Any:
        try:
            response = self._client.request(method, **self._request_options(path, tenant, **kwargs))
        except httpx.TransportError as exc:
            raise StoreError("Caura transport failure", retryable=True) from exc
        return _decode(response, writing=writing)

    def _resolve(self, scope: MemoryScope) -> str:
        tenant = self._tenant(scope)
        if tenant is None:
            identity = _object(self._request("GET", "/api/v1/whoami"))
            self._tenant_id = _string(identity.get("tenant_id"))
            tenant = self._tenant_id
        return tenant

    def recall(self, query: str, scope: MemoryScope, top_k: int = 8) -> list[Fact]:
        tenant = self._resolve(scope)
        return _facts(
            self._request(
                "POST",
                "/api/v1/search",
                tenant=tenant,
                json=self._search(query, scope, tenant, top_k),
            )
        )

    def keystones(self, scope: MemoryScope) -> list[KeystoneRule]:
        tenant = self._resolve(scope)
        return _keystones(
            self._request(
                "GET",
                "/api/v1/keystones",
                tenant=tenant,
                params=self._rule_params(scope, tenant),
            )
        )

    def write(self, fact: str, scope: MemoryScope) -> WriteResult:
        tenant = self._resolve(scope)
        return _written(
            self._request(
                "POST",
                "/api/v1/memories",
                tenant=tenant,
                writing=True,
                json=self._write(fact, scope, tenant),
            )
        )

    def close(self) -> None:
        """Close the HTTP client if this store created it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self: _SyncT) -> _SyncT:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AsyncRestMemoryStore(_Config):
    """Asynchronous Caura REST client. Use as an async context manager to close it."""

    def __init__(self, *args: Any, client: httpx.AsyncClient | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        tenant: str | None = None,
        writing: bool = False,
        **kwargs: Any,
    ) -> Any:
        try:
            response = await self._client.request(
                method, **self._request_options(path, tenant, **kwargs)
            )
        except httpx.TransportError as exc:
            raise StoreError("Caura transport failure", retryable=True) from exc
        return _decode(response, writing=writing)

    async def _resolve(self, scope: MemoryScope) -> str:
        tenant = self._tenant(scope)
        if tenant is None:
            identity = _object(await self._request("GET", "/api/v1/whoami"))
            self._tenant_id = _string(identity.get("tenant_id"))
            tenant = self._tenant_id
        return tenant

    async def recall(self, query: str, scope: MemoryScope, top_k: int = 8) -> list[Fact]:
        tenant = await self._resolve(scope)
        return _facts(
            await self._request(
                "POST",
                "/api/v1/search",
                tenant=tenant,
                json=self._search(query, scope, tenant, top_k),
            )
        )

    async def keystones(self, scope: MemoryScope) -> list[KeystoneRule]:
        tenant = await self._resolve(scope)
        return _keystones(
            await self._request(
                "GET",
                "/api/v1/keystones",
                tenant=tenant,
                params=self._rule_params(scope, tenant),
            )
        )

    async def write(self, fact: str, scope: MemoryScope) -> WriteResult:
        tenant = await self._resolve(scope)
        return _written(
            await self._request(
                "POST",
                "/api/v1/memories",
                tenant=tenant,
                writing=True,
                json=self._write(fact, scope, tenant),
            )
        )

    async def aclose(self) -> None:
        """Close the HTTP client if this store created it."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self: _AsyncT) -> _AsyncT:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
