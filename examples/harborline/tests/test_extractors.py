"""Unit tests that do not need a live Caura server."""

from __future__ import annotations


def _load_intake_extractor():
    """Mirror of intake/src/agent.ts extractor for fast unit checks."""
    from caura_rail import rule_extract

    def intake_extractor(message: str, reply: str) -> list[str]:
        from_default = rule_extract(message, reply)
        notes = []
        for line in message.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("customer note:"):
                text = "Customer note: " + stripped.split(":", 1)[1].strip()
                if len(text) >= 10:
                    notes.append(text)
        seen = {f.lower() for f in from_default}
        merged = list(from_default)
        for note in notes:
            if note.lower() not in seen:
                seen.add(note.lower())
                merged.append(note)
        return merged

    return intake_extractor


def test_intake_extractor_merges_default_and_customer_notes():
    extract = _load_intake_extractor()
    facts = extract(
        "Remember: We deploy webhooks in us-east-1 for Acme.\n"
        "Customer note: Acme on-call is #ops-acme.\n"
        "hello there",
        "ok",
    )
    assert any("us-east-1" in f for f in facts)
    assert any(f.startswith("Customer note:") for f in facts)
    assert all(not f.lower().startswith("remember:") for f in facts)


def test_decisions_only_extractor():
    from backend.specialist import decisions_only

    assert decisions_only("Decision: freeze the merchant overnight.", "x") == [
        "Decision: freeze the merchant overnight."
    ]
    assert decisions_only("Remember: should not store", "x") == []


def test_load_settings_oss(monkeypatch, tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "oss.env").write_text("CAURA_URL=http://localhost:8000\nCAURA_API_KEY=standalone\n")
    (secrets / "llm.env").write_text("OPENAI_API_KEY=\n")

    import backend.config as config

    monkeypatch.setattr(config, "SECRETS", secrets)
    monkeypatch.setenv("CAURA_BACKEND", "oss")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CAURA_TENANT", raising=False)

    settings = config.load_settings()
    assert settings.backend == "oss"
    assert settings.caura_url == "http://localhost:8000"
    assert settings.openai_api_key in (None, "")
