"""Load CAURA_BACKEND + secrets/*.env and shared demo settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "secrets"


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        raise FileNotFoundError(f"Missing secrets file: {path}")
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    backend: str  # oss | saas
    caura_url: str
    caura_api_key: str
    caura_tenant: str | None
    rule_author_key: str | None
    rule_author_agent: str | None
    openai_api_key: str | None
    intake_url: str
    demo_marker: str


def load_settings() -> Settings:
    backend = os.environ.get("CAURA_BACKEND", "oss").strip().lower()
    if backend not in {"oss", "saas"}:
        raise ValueError("CAURA_BACKEND must be 'oss' or 'saas'")

    caura = _load_env_file(SECRETS / f"{backend}.env")
    llm = {}
    llm_path = SECRETS / "llm.env"
    if llm_path.is_file():
        llm = _load_env_file(llm_path)

    # Apply into process env so Rail's from_env / fromEnv see them.
    os.environ["CAURA_URL"] = caura["CAURA_URL"]
    os.environ["CAURA_API_KEY"] = caura["CAURA_API_KEY"]
    if caura.get("CAURA_TENANT"):
        os.environ["CAURA_TENANT"] = caura["CAURA_TENANT"]
    elif "CAURA_TENANT" in os.environ:
        # Avoid leaking a tenant pin from a previous backend selection.
        del os.environ["CAURA_TENANT"]

    force_deterministic = os.environ.get("DEMO_FORCE_DETERMINISTIC", "").strip() == "1"
    openai_key = (
        None
        if force_deterministic
        else (os.environ.get("OPENAI_API_KEY") or llm.get("OPENAI_API_KEY") or None)
    )
    if openai_key and openai_key.strip():
        os.environ["OPENAI_API_KEY"] = openai_key.strip()
        openai_key = openai_key.strip()
    else:
        openai_key = None
        os.environ.pop("OPENAI_API_KEY", None)

    return Settings(
        backend=backend,
        caura_url=caura["CAURA_URL"].rstrip("/"),
        caura_api_key=caura["CAURA_API_KEY"],
        caura_tenant=caura.get("CAURA_TENANT") or None,
        rule_author_key=caura.get("CAURA_RULE_AUTHOR_KEY") or None,
        rule_author_agent=caura.get("CAURA_RULE_AUTHOR_AGENT") or None,
        openai_api_key=openai_key or None,
        intake_url=os.environ.get("INTAKE_URL", "http://127.0.0.1:8787").rstrip("/"),
        demo_marker=os.environ.get("DEMO_MARKER", "harborline-demo"),
    )
