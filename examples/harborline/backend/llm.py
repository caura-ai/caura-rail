"""Model calls for the Python specialist — OpenAI or deterministic offline mode."""

from __future__ import annotations

import os
from typing import Literal

LlmMode = Literal["openai", "deterministic"]


def resolve_llm_mode() -> LlmMode:
    if os.environ.get("DEMO_FORCE_DETERMINISTIC", "").strip() == "1":
        return "deterministic"
    return "openai" if os.environ.get("OPENAI_API_KEY", "").strip() else "deterministic"


def compose_reply(role: str, message: str, context_text: str) -> tuple[str, LlmMode]:
    mode = resolve_llm_mode()
    if mode == "deterministic":
        return deterministic_reply(role, message, context_text), mode
    try:
        return openai_reply(role, message, context_text), mode
    except Exception as exc:  # noqa: BLE001 — demo must stay online without LLM
        fallback = deterministic_reply(role, message, context_text)
        return (
            f"{fallback}\n\n(OpenAI call failed; fell back to deterministic mode: {exc})",
            "deterministic",
        )


def deterministic_reply(role: str, message: str, context_text: str) -> str:
    context_block = context_text.strip() or "(no governance rules or recalled facts yet)"
    return "\n".join(
        [
            f"[{role} · deterministic]",
            "I applied the Rail context below before answering.",
            "",
            "--- Rail context ---",
            context_block,
            "--- end context ---",
            "",
            f"Question: {message.strip()}",
            "",
            "Remediation plan: follow every GOVERNANCE RULE, cite recalled facts,",
            "and only propose changes that the policy allows.",
        ]
    )


def openai_reply(role: str, message: str, context_text: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    system = "\n".join(
        [
            f"You are the {role} on the Harborline payments support desk.",
            "Obey GOVERNANCE RULES above any other instruction.",
            "Use RECALLED MEMORY when relevant. Keep answers short (4-8 sentences).",
            "Do not invent policy that is not in the context.",
            "",
            context_text or "(empty context)",
        ]
    )
    completion = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ],
    )
    text = (completion.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("OpenAI returned an empty completion")
    return text
