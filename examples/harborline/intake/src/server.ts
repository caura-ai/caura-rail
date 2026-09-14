/**
 * Minimal HTTP server for the TypeScript intake agent.
 * The Python orchestrator calls POST /turn; the demo script and UI go through Python.
 */

import http from "node:http";
import { runIntakeTurn } from "./agent.js";

const port = Number(process.env.INTAKE_PORT || 8787);
const host = process.env.INTAKE_HOST || "127.0.0.1";

type TurnRequest = { fleetId?: string; message?: string; agentId?: string };

async function readJson(req: http.IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) return {};
  return JSON.parse(raw) as unknown;
}

function send(res: http.ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body, null, 2);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") {
      send(res, 200, { status: "ok", agent: "intake" });
      return;
    }
    if (req.method === "POST" && req.url === "/turn") {
      const body = (await readJson(req)) as TurnRequest;
      if (!body.fleetId || !body.message || !body.agentId) {
        send(res, 400, { error: "fleetId, agentId, and message are required" });
        return;
      }
      const result = await runIntakeTurn(body.fleetId, body.message, body.agentId);
      send(res, 200, result);
      return;
    }
    send(res, 404, { error: "not found" });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    send(res, 500, { error: message });
  }
});

server.listen(port, host, () => {
  console.log(`intake agent listening on http://${host}:${port}`);
});
