/**
 * Harborline intake agent — TypeScript side of the Rail demo.
 *
 * First-line support: recalls fleet memory, answers the customer, and stores
 * durable notes via a custom extractor that extends Rail's default prefixes
 * with "Customer note:" lines used by support scripts.
 */

import {
  MemoryScope,
  Rail,
  RestMemoryStore,
  ruleExtract,
  type Extractor,
  type TurnResult,
} from "@caura/rail";
import { composeReply } from "./llm.js";

/** Default prefixes plus support-desk "Customer note:" lines (prefix kept). */
export const intakeExtractor: Extractor = (message, reply) => {
  const fromDefault = ruleExtract(message, reply);
  const notes = message
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => /^customer note:/i.test(line))
    .map((line) => line.replace(/^customer note:\s*/i, "Customer note: ").trim())
    .filter((line) => line.length >= 10);
  const seen = new Set(fromDefault.map((f) => f.toLowerCase()));
  const merged = [...fromDefault];
  for (const note of notes) {
    const key = note.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      merged.push(note);
    }
  }
  return merged;
};

export type TurnPayload = {
  agentId: string;
  fleetId: string;
  message: string;
  reply: string;
  llmMode: string;
  degraded: boolean;
  errors: string[];
  context: {
    text: string;
    degraded: boolean;
    errors: string[];
    keystones: Array<{ docId: string; title: string; content: string; weight: number }>;
    facts: Array<{ id: string; content: string; agentId: string }>;
  };
  writes: Array<{ status: string; id?: string | null; error?: string | null }>;
  telemetry: {
    turnsTotal: number;
    degradedTurns: number;
    writesDeferred: number;
    writesRejected: number;
    extractionFailures: number;
  };
};

function serializeTurn(
  agentId: string,
  fleetId: string,
  message: string,
  turn: TurnResult,
  llmMode: string,
  rail: Rail,
): TurnPayload {
  return {
    agentId,
    fleetId,
    message,
    reply: turn.reply,
    llmMode,
    degraded: turn.degraded,
    errors: [...turn.errors],
    context: {
      text: turn.context.text,
      degraded: turn.context.degraded,
      errors: [...turn.context.errors],
      keystones: turn.context.keystones.map((k) => ({
        docId: k.docId,
        title: k.title,
        content: k.content,
        weight: k.weight,
      })),
      facts: turn.context.facts.map((f) => ({
        id: f.id,
        content: f.content,
        agentId: f.agentId,
      })),
    },
    writes: turn.writes.map((w) => ({
      status: w.status,
      id: w.id ?? null,
      error: w.error ?? null,
    })),
    telemetry: {
      turnsTotal: rail.telemetry.turnsTotal,
      degradedTurns: rail.telemetry.degradedTurns,
      writesDeferred: rail.telemetry.writesDeferred,
      writesRejected: rail.telemetry.writesRejected,
      extractionFailures: rail.telemetry.extractionFailures,
    },
  };
}

export async function runIntakeTurn(
  fleetId: string,
  message: string,
  agentId: string,
): Promise<TurnPayload> {
  if (!fleetId.startsWith("demo-")) {
    throw new Error("fleetId must start with demo-");
  }
  if (!agentId.trim()) {
    throw new Error("agentId is required");
  }
  const store = RestMemoryStore.fromEnv(process.env, { timeoutMs: 30000 });
  const scope = new MemoryScope({
    agentId,
    fleetId,
    visibility: "scope_team",
  });
  const rail = new Rail({
    store,
    scope,
    extractor: intakeExtractor,
    topK: 10,
  });

  const turn = await rail.turn(message, async (_msg, context) => {
    const { reply } = await composeReply("intake", message, context.text);
    return reply;
  });

  if (turn.writes.some((w) => w.status === "deferred")) {
    await rail.flushOutbox(2);
  }

  return serializeTurn(agentId, fleetId, message, turn, resolveModeLabel(), rail);
}

function resolveModeLabel(): string {
  if (process.env.DEMO_FORCE_DETERMINISTIC === "1") return "deterministic";
  return process.env.OPENAI_API_KEY?.trim() ? "openai" : "deterministic";
}
