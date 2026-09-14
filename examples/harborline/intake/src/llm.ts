/**
 * Shared reply helpers for the intake agent.
 * Deterministic replies keep the demo offline-capable without OPENAI_API_KEY.
 */

export type LlmMode = "openai" | "deterministic";

export function resolveLlmMode(): LlmMode {
  if (process.env.DEMO_FORCE_DETERMINISTIC === "1") return "deterministic";
  return process.env.OPENAI_API_KEY?.trim() ? "openai" : "deterministic";
}

export async function composeReply(
  role: string,
  message: string,
  contextText: string,
): Promise<{ reply: string; mode: LlmMode }> {
  const mode = resolveLlmMode();
  if (mode === "deterministic") {
    return { reply: deterministicReply(role, message, contextText), mode };
  }
  try {
    const reply = await openaiReply(role, message, contextText);
    return { reply, mode };
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    return {
      reply: deterministicReply(role, message, contextText) +
        `\n\n(OpenAI call failed; fell back to deterministic mode: ${detail})`,
      mode: "deterministic",
    };
  }
}

function deterministicReply(role: string, message: string, contextText: string): string {
  const contextBlock = contextText.trim()
    ? contextText.trim()
    : "(no governance rules or recalled facts yet)";
  return [
    `[${role} · deterministic]`,
    "I read the Rail context below, then answered the customer.",
    "",
    "--- Rail context ---",
    contextBlock,
    "--- end context ---",
    "",
    `Customer said: ${message.trim()}`,
    "",
    "Next step: capture durable facts, then escalate to the specialist if the",
    "issue needs policy-bound remediation.",
  ].join("\n");
}

async function openaiReply(role: string, message: string, contextText: string): Promise<string> {
  const key = process.env.OPENAI_API_KEY!;
  const system = [
    `You are the ${role} assistant on the Harborline payments support desk.`,
    "Obey any GOVERNANCE RULES in the context. Use RECALLED MEMORY when relevant.",
    "Keep answers short (3-6 sentences). Do not invent policy that is not in context.",
    "",
    contextText || "(empty context)",
  ].join("\n");

  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: process.env.OPENAI_MODEL || "gpt-4o-mini",
      temperature: 0.2,
      messages: [
        { role: "system", content: system },
        { role: "user", content: message },
      ],
    }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`OpenAI HTTP ${res.status}: ${body.slice(0, 200)}`);
  }
  const data = (await res.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const text = data.choices?.[0]?.message?.content?.trim();
  if (!text) throw new Error("OpenAI returned an empty completion");
  return text;
}
