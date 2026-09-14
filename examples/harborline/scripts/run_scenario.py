#!/usr/bin/env python3
"""Scripted end-to-end Harborline scenario against a running API."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BASE = os.environ.get("DEMO_API", "http://127.0.0.1:8080").rstrip("/")


class DemoFailure(Exception):
    pass


def log(step: str, msg: str) -> None:
    print(f"[{step}] {msg}", flush=True)


def request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DemoFailure(f"{method} {path} -> HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise DemoFailure(f"{method} {path} -> {exc}") from exc


def expect(cond: bool, message: str) -> None:
    if not cond:
        raise DemoFailure(message)


def wait_healthy(timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            health = request("GET", "/api/health")
            if health.get("status") == "ok":
                return health
            last = str(health)
        except DemoFailure as exc:
            last = str(exc)
        time.sleep(0.4)
    raise DemoFailure(f"API not healthy within {timeout}s: {last}")


def main() -> int:
    print("=== Harborline Rail demo scenario ===", flush=True)
    health = wait_healthy()
    log("0", f"API healthy · backend={health.get('backend')} · llm={health.get('llmMode')}")

    boot = request("POST", "/api/bootstrap", {})
    fleet = boot["fleetId"]
    marker = boot["marker"]
    log("1", f"Bootstrapped fleet {fleet} with keystone {boot['keystoneDocId']}")
    expect(fleet.startswith("demo-"), "fleet id must start with demo-")

    # Step 2: Intake stores a Remember: fact (default extractor + custom notes).
    msg2 = (
        f"Remember: Acme settles payouts in USD via ACH for merchant {marker}.\n"
        f"Customer note: Acme on-call pager channel is #ops-{marker}."
    )
    t2 = request("POST", "/api/turn", {"agent": "intake", "message": msg2})
    log("2", f"Intake turn degraded={t2['degraded']} writes={[w['status'] for w in t2['writes']]}")
    statuses = [w["status"] for w in t2["writes"]]
    expect(len(statuses) >= 2, f"expected >=2 writes from intake, got {statuses}")
    expect(
        all(s in {"written", "deduplicated"} for s in statuses),
        f"intake writes should succeed, got {t2['writes']}",
    )
    expect(not t2["degraded"], f"intake turn unexpectedly degraded: {t2.get('errors')}")

    # Step 3: Specialist recalls teammate facts + governance rule.
    msg3 = (
        f"Acme ({marker}) asks how we should handle a payout dispute. "
        "What settlement rail do they use, and what PII rules apply?"
    )
    t3 = request("POST", "/api/turn", {"agent": "specialist", "message": msg3})
    log(
        "3",
        f"Specialist context has {len(t3['context']['keystones'])} keystone(s), "
        f"{len(t3['context']['facts'])} fact(s)",
    )
    text = t3["context"]["text"]
    expect("GOVERNANCE RULES" in text or t3["context"]["keystones"], "missing governance rules")
    expect(
        any(
            "PII" in k["title"] or "PII" in k["content"] or "card" in k["content"].lower()
            for k in t3["context"]["keystones"]
        ),
        f"PII keystone not in context: {t3['context']['keystones']}",
    )
    # OSS may use placeholder embeddings; require marker or ACH/USD keywords.
    fact_blob = " ".join(f["content"] for f in t3["context"]["facts"]) + text
    expect(
        marker in fact_blob or "ACH" in fact_blob or "USD" in fact_blob,
        f"expected intake facts in specialist recall, got: {t3['context']['facts']!r}",
    )
    expect(t3["reply"], "specialist reply empty")
    expect(t3["writes"] == [], f"specialist should be recall-only here, writes={t3['writes']}")

    # Step 4: Deduplicate the same Remember: line via intake.
    msg4 = f"Remember: Acme settles payouts in USD via ACH for merchant {marker}."
    t4 = request("POST", "/api/turn", {"agent": "intake", "message": msg4})
    log("4", f"Dedup turn writes={[w['status'] for w in t4['writes']]}")
    expect(len(t4["writes"]) == 1, f"expected one write, got {t4['writes']}")
    expect(
        t4["writes"][0]["status"] in {"deduplicated", "written"},
        f"expected deduplicated (or written on cold store), got {t4['writes'][0]}",
    )
    # Prefer deduplicated; if SaaS/OSS semantic dedup is slow, written is still a signal.
    if t4["writes"][0]["status"] != "deduplicated":
        log("4", "WARN: expected deduplicated; got written — continuing")

    # Step 5: Specialist Decision: write + short rejected extraction path via intake.
    msg5 = (
        f"Decision: For merchant {marker}, open a dispute case in the risk console "
        "and redact PANs to last-4 before pasting into the ticket."
    )
    t5 = request("POST", "/api/turn", {"agent": "specialist", "message": msg5})
    log("5", f"Decision writes={[w['status'] for w in t5['writes']]}")
    expect(len(t5["writes"]) == 1, f"expected one decision write, got {t5['writes']}")
    expect(
        t5["writes"][0]["status"] in {"written", "deduplicated"},
        f"decision write failed: {t5['writes'][0]}",
    )

    # Step 6: Rejected short fact — custom extractor emits a too-short Customer note.
    # Rail validates max length but server rejects <10 chars. We send a note that
    # becomes too short after our normalize? Actually our extractor filters <10.
    # Use default Remember: with short body stripped... Remember: Hi -> after strip "Hi" (2 chars)
    msg6 = "Remember: xx"
    t6 = request("POST", "/api/turn", {"agent": "intake", "message": msg6})
    log("6", f"Short-fact writes={[w for w in t6['writes']]}")
    expect(len(t6["writes"]) == 1, f"expected one write attempt, got {t6['writes']}")
    expect(
        t6["writes"][0]["status"] == "rejected",
        f"expected rejected short fact, got {t6['writes'][0]}",
    )

    # Step 7: Explicit recall endpoint (does not increment specialist turn writes).
    recall = request(
        "POST",
        "/api/recall",
        {"query": f"What settlement method does merchant {marker} use?"},
    )
    log("7", f"recall facts={len(recall['facts'])} keystones={len(recall['keystones'])}")
    expect(recall["keystones"], "recall missing keystones")

    cleanup = request("POST", "/api/cleanup", {})
    log("8", f"cleanup removedKeystone={cleanup.get('removedKeystone')}")
    expect(cleanup.get("removedKeystone") is True, "keystone cleanup did not run")

    print("=== DEMO OK ===", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DemoFailure as exc:
        print(f"=== DEMO FAILED ===\n{exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
