"""Verify both installed clients over HTTP, using a local contract fixture."""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from caura_rail import MemoryScope, Rail, RestMemoryStore, Visibility

FIXTURE = json.loads(Path(__file__).with_name("caura.json").read_text())


def main():
    memories = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("X-API-Key") != "contract-key":
                return self.reply(401, {"detail": "Unauthorized"})
            path = urlparse(self.path).path
            if path == "/whoami":
                return self.reply(200, FIXTURE["identity"])
            if path == "/api/v1/keystones":
                return self.reply(200, FIXTURE["keystones_response"])
            self.reply(404, {})

        def do_POST(self):
            if self.headers.get("X-API-Key") != "contract-key":
                return self.reply(401, {"detail": "Unauthorized"})
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if data.get("tenant_id") != FIXTURE["tenant"]:
                return self.reply(403, {"detail": "Tenant mismatch"})
            with lock:
                if self.path == "/api/v1/memories":
                    if data.get("visibility") != "scope_team" or data.get("fleet_id") != "support":
                        return self.reply(422, {"detail": "Expected team-scoped fixture write"})
                    record = {"id": str(len(memories) + 1), **data}
                    memories.append(record)
                    return self.reply(201, record)
                if self.path == "/api/v1/search":
                    if "caller_agent_id" not in data or data.get("fleet_ids") != ["support"]:
                        return self.reply(422, {"detail": "Expected scoped search contract"})
                    return self.reply(200, {"items": list(memories)})
            self.reply(404, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(server.server_port)
    try:
        scope = MemoryScope(
            agent_id="python-agent", fleet_id="support", visibility=Visibility.TEAM
        )
        with RestMemoryStore(base_url=url, api_key="contract-key") as store:
            rail = Rail(store, scope)
            with rail.turn("Remember: Python learned the deployment region.") as turn:
                if turn.degraded:
                    raise RuntimeError("Contract recall degraded")
                turn.reply = "Recorded"
            assert turn.writes[0].status == "written"
            subprocess.run(
                ["node", str(Path(__file__).with_name("peer.mjs")), url],
                check=True, timeout=30,
            )
            ctx = rail.recall("What did TypeScript learn?")
            assert not ctx.degraded
            assert any(f.content == "TypeScript learned the renewal date." for f in ctx.facts)
            assert len(ctx.keystones) == 2
        print("Python -> HTTP -> TypeScript -> HTTP -> Python contract round trip passed.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
