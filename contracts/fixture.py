"""A loopback HTTP fixture that mirrors the Caura REST contract used by Rail.

It implements identity discovery, keystones, search, and memory writes with
the same status codes, field names, limits, and error envelopes as the Caura
server. It is not a search engine: search returns stored memories that share a
word with the query, newest first. Nothing persists beyond the process.
"""

import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

FIXTURE: dict[str, Any] = json.loads(Path(__file__).with_name("caura.json").read_text())
API_KEY = "contract-key"
TENANT = FIXTURE["tenant"]
VISIBILITIES = {"scope_agent", "scope_team", "scope_org"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w-]+", text.lower()))


def duplicate_error(existing: dict[str, Any]) -> dict[str, Any]:
    message = "Duplicate memory exists: " + existing["id"]
    return {
        "detail": message,
        "error": {
            "code": "DUPLICATE_MEMORY",
            "message": message,
            "details": {
                "reason": "exact_content_hash",
                "existing_id": existing["id"],
                "existing_status": "active",
            },
        },
    }


class CauraFixture:
    """In-memory state shared by every request handler of one server."""

    def __init__(self) -> None:
        self.memories: list[dict[str, Any]] = []
        self.keystones: list[dict[str, Any]] = list(FIXTURE["keystones_response"])
        self.requests: list[tuple[str, str]] = []
        self.lock = threading.Lock()

    def write(self, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        content = data.get("content")
        if not isinstance(content, str) or not 10 <= len(content.strip()) <= 10000:
            return 422, {"detail": "Memory content must be 10 to 10000 characters."}
        if not isinstance(data.get("agent_id"), str) or not data["agent_id"]:
            return 422, {"detail": "agent_id is required"}
        if data.get("visibility") not in VISIBILITIES:
            return 422, {"detail": "Invalid visibility"}
        if data.get("visibility") == "scope_team" and not data.get("fleet_id"):
            return 422, {"detail": "scope_team requires fleet_id"}
        for existing in self.memories:
            if existing["content"] == content and existing.get("fleet_id") == data.get("fleet_id"):
                return 409, duplicate_error(existing)
        record = {"id": str(uuid4()), "status": "active", **data}
        self.memories.append(record)
        return 201, record

    def search(self, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = data.get("query")
        if not isinstance(query, str) or not 1 <= len(query) <= 5000:
            return 422, {"detail": "query must be 1 to 5000 characters"}
        top_k = data.get("top_k", 5)
        if type(top_k) is not int or not 1 <= top_k <= 20:
            return 422, {"detail": "top_k must be between 1 and 20"}
        if "caller_agent_id" not in data:
            return 422, {"detail": "caller_agent_id is required for scoped recall"}
        fleets = data.get("fleet_ids")
        if fleets is not None and not isinstance(fleets, list):
            return 422, {"detail": "fleet_ids must be a list"}
        visible = [
            m
            for m in reversed(self.memories)
            if m["agent_id"] == data["caller_agent_id"]
            or (
                m.get("visibility") != "scope_agent" and (not fleets or m.get("fleet_id") in fleets)
            )
        ]
        matching = [m for m in visible if _words(query) & _words(m["content"])]
        return 200, {"items": matching[:top_k], "recall_tracked": False}


class _Handler(BaseHTTPRequestHandler):
    fixture: CauraFixture

    def log_message(self, *_: Any) -> None:
        pass

    def reply(self, status: int, value: Any) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        if self.headers.get("X-API-Key") != API_KEY:
            self.reply(401, {"detail": "Invalid API key."})
            return False
        return True

    def do_GET(self) -> None:
        url = urlparse(self.path)
        self.fixture.requests.append(("GET", url.path))
        if not self.authorized():
            return
        if url.path == "/api/v1/whoami":
            return self.reply(200, FIXTURE["identity"])
        if url.path == "/api/v1/keystones":
            params = parse_qs(url.query)
            if params.get("tenant_id") != [TENANT]:
                return self.reply(403, {"detail": "API key is not authorized to read tenant"})
            with self.fixture.lock:
                return self.reply(200, list(self.fixture.keystones))
        self.reply(404, {"detail": "Not Found"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        self.fixture.requests.append(("POST", url.path))
        if not self.authorized():
            return
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if data.get("tenant_id") != TENANT or self.headers.get("X-Tenant-ID") != TENANT:
            return self.reply(403, {"detail": "API key is not authorized to read tenant"})
        with self.fixture.lock:
            if url.path == "/api/v1/memories":
                return self.reply(*self.fixture.write(data))
            if url.path == "/api/v1/search":
                return self.reply(*self.fixture.search(data))
        self.reply(404, {"detail": "Not Found"})


@contextmanager
def serve() -> Iterator[tuple[str, CauraFixture]]:
    """Run the fixture on an ephemeral loopback port; yields (base_url, state)."""
    state = CauraFixture()
    handler = type("Handler", (_Handler,), {"fixture": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    import signal

    with serve() as (url, _):
        print("Caura fixture listening at", url, flush=True)
        signal.pause()
