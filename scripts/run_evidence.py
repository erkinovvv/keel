"""Produce the execution-evidence pack: full advisory sessions on the simulated account.

    scripts/fisco_chain.sh start            # for real FISCO BCOS anchors (otherwise anchors are skipped)
    uv run python scripts/run_evidence.py   # writes evidence/<scenario>/ and evidence/INDEX.md

Each scenario drives the same HTTP API the web UI uses (FastAPI TestClient), with the real fund
catalog. Per scenario it saves the hash-chained audit log, a step-by-step transcript of requests and
responses, the account statement, the FISCO BCOS anchor with its verification, and the Advice Report.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
OUT = ROOT / "evidence"


class Recorder:
    def __init__(self, client, folder: Path):
        self.client, self.folder, self.steps = client, folder, []

    def call(self, label: str, method: str, path: str, body: dict | None = None, expect: int | None = 200) -> Any:
        response = self.client.request(method, path, json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = {"html_bytes": len(response.text)}
        self.steps.append({"step": label, "request": {"method": method, "path": path, "body": body}, "status": response.status_code, "response": payload})
        if expect is not None and response.status_code != expect:
            raise AssertionError(f"{label}: expected {expect}, got {response.status_code}: {str(payload)[:200]}")
        return payload


def _answers(questions: list[dict], picks: dict[str, int]) -> dict[str, str]:
    """picks: question -> option index (negative = from the riskiest end)."""

    return {q["key"]: q["options"][picks.get(q["key"], len(q["options"]) // 2)]["key"] for q in questions}


def _execute(rec: Recorder, signer: str) -> dict[str, Any]:
    rec.call("Sign risk disclosure (moves session from advice-only to simulated trading)", "POST", "/api/consent", {"full_name": signer, "accepted": True})
    drafts = rec.call("Create draft orders (pre-trade checks on the server)", "POST", "/api/orders/draft")
    now = [o["order_id"] for o in drafts["orders"] if not o["cooling_off"]]
    tokens = rec.call("Human holds confirm: issue one-time tokens", "POST", "/api/orders/tokens", {"order_ids": now})["tokens"]
    return rec.call("Confirm orders with the tokens", "POST", "/api/orders/confirm", {"tokens": tokens})


def _anchor(rec: Recorder) -> dict[str, Any]:
    anchor = rec.call("Anchor the audit-chain head on FISCO BCOS", "POST", "/api/anchor", expect=None)
    if isinstance(anchor, dict) and anchor.get("sent"):
        anchor["verification"] = rec.call("Verify the anchor against the local audit chain", "GET", f"/api/anchor/verify?tx={anchor['tx_hash']}")
    return anchor


def scenario_conservative(rec: Recorder) -> dict[str, Any]:
    questions = rec.call("Load questionnaire", "GET", "/api/questionnaire")
    picks = {"horizon": 1, "liquidity_need": 1, "income_stability": 1, "emergency_fund": 1, "invested_share": 1, "drawdown_reaction": 1, "experience": 1, "goal": 1}
    profile = rec.call("Assess risk profile (age 66, 200,000, 5-year horizon, 8% loss limit)", "POST", "/api/profile",
                       {"answers": _answers(questions, picks), "age": 66, "amount": 200_000, "horizon_years": 5, "max_loss": 0.08})
    rec.call("Build allocation", "POST", "/api/allocation", {})
    rec.call("Compare suitable products", "GET", "/api/compare")
    rec.call("Stress test against the client's limit", "GET", "/api/stress")
    rec.call("Goal: 220,000 in 5 years", "POST", "/api/goal", {"target": 220_000, "years": 5, "monthly": 500})
    confirm = _execute(rec, "Evidence Client One")
    return {"class": profile["profile"]["investor_class"], "executed": len(confirm["executed"]), "total": confirm["total"]}


def scenario_rehearsal(rec: Recorder) -> dict[str, Any]:
    questions = rec.call("Load questionnaire", "GET", "/api/questionnaire")
    picks = {q["key"]: len(q["options"]) - 1 for q in questions}  # most risk-tolerant answers
    profile = rec.call("Assess risk profile (age 27, 100,000, 15-year horizon, 25% loss limit)", "POST", "/api/profile",
                       {"answers": _answers(questions, picks), "age": 27, "amount": 100_000, "horizon_years": 15, "max_loss": 0.25})
    rec.call("Build allocation at the questionnaire class", "POST", "/api/allocation", {})
    replay = rec.call("Crash Rehearsal: replay 2007-2013 with this portfolio", "GET", "/api/rehearsal")
    sell_at = next(i for i, p in enumerate(replay["points"]) if p["drawdown"] > 0.10)
    outcome = rec.call(f"Client presses Sell in {replay['points'][sell_at]['month']}", "POST", "/api/rehearsal/decision", {"action": "sell", "month_index": sell_at})
    attempt = rec.call("Try to build at the old, higher class (must be refused)", "POST", "/api/allocation", {"investor_class": profile["profile"]["investor_class"]}, expect=None)
    rec.call("Rebuild at the revealed class", "POST", "/api/allocation", {})
    confirm = _execute(rec, "Evidence Client Two")
    return {
        "class_before": profile["profile"]["investor_class"],
        "class_after": outcome["profile"]["investor_class"],
        "old_class_request_status": rec.steps[-6]["status"] if attempt is not None else None,
        "executed": len(confirm["executed"]),
        "total": confirm["total"],
    }


def scenario_controls(rec: Recorder) -> dict[str, Any]:
    questions = rec.call("Load questionnaire", "GET", "/api/questionnaire")
    profile = rec.call("Assess risk profile", "POST", "/api/profile", {"answers": _answers(questions, {}), "age": 35, "amount": 50_000, "horizon_years": 8, "max_loss": 0.15})
    level = profile["profile"]["investor_class"]
    results = {}
    results["above_class_allocation"] = rec.call("Request a portfolio above the assessed class", "POST", "/api/allocation", {"investor_class": min(5, level + 1)}, expect=403 if level < 5 else 200)
    rec.call("Build allocation", "POST", "/api/allocation", {})
    rec.call("Draft orders without a signed disclosure (must be refused)", "POST", "/api/orders/draft", expect=403)
    rec.call("Sign risk disclosure", "POST", "/api/consent", {"full_name": "Evidence Client Three", "accepted": True})
    drafts = rec.call("Create draft orders", "POST", "/api/orders/draft")
    order_id = next(o["order_id"] for o in drafts["orders"] if not o["cooling_off"])
    forged = rec.call("Confirm with a forged token (must execute nothing)", "POST", "/api/orders/confirm", {"tokens": {order_id: "forged-token"}})
    tokens = rec.call("Issue a genuine token", "POST", "/api/orders/tokens", {"order_ids": [order_id]})["tokens"]
    rec.call("Confirm with the genuine token", "POST", "/api/orders/confirm", {"tokens": tokens})
    replay = rec.call("Replay the same token (must execute nothing)", "POST", "/api/orders/confirm", {"tokens": tokens})
    redacted = rec.call("PII masking preview before any model call", "POST", "/api/redact", {"message": "My passport number is K1234567 and my card is 6222 0212 3456 7890 123"})
    return {
        "forged_token_executed": len(forged["executed"]),
        "replayed_token_executed": len(replay["executed"]),
        "redacted_message": redacted["redacted"],
    }


SCENARIOS = {
    "01-conservative-client": ("A cautious 66-year-old: profiling, allocation within an 8% loss limit, comparison, stress test, goal, signed disclosure, hold-to-confirm execution.", scenario_conservative),
    "02-crash-rehearsal": ("A self-declared aggressive investor sells during the 2008 replay; the class is lowered, the old portfolio is refused, a suitable one is rebuilt and executed.", scenario_rehearsal),
    "03-controls": ("Server-side controls: above-class request, trading before consent, forged and replayed confirmation tokens, PII masking.", scenario_controls),
}


def main() -> None:
    os.environ.setdefault("WEALTH_ADVISOR_CATALOG", "cn")
    os.environ.setdefault("ANCHOR_NETWORK", "fisco")
    os.environ.setdefault("LLM_MODE", "replay")
    from fastapi.testclient import TestClient

    from wealth_advisor.audit import verify_audit_log
    from wealth_advisor.ui.server import app

    if OUT.exists():
        shutil.rmtree(OUT)
    index = ["# Execution evidence", "", f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `uv run python scripts/run_evidence.py` on the simulated brokerage account, real Chinese fund catalog, local FISCO BCOS 3.17 consortium chain.", ""]
    index += ["| Scenario | What it shows | Result | Audit chain | FISCO BCOS anchor |", "|---|---|---|---|---|"]
    for name, (summary, run) in SCENARIOS.items():
        folder = OUT / name
        folder.mkdir(parents=True)
        os.environ["AUDIT_LOG"] = str(folder / "audit.jsonl")
        client = TestClient(app)
        rec = Recorder(client, folder)
        result = run(rec)
        anchor = _anchor(rec)
        statement = rec.call("Account and session state", "GET", "/api/state")
        report = client.get("/report")
        (folder / "advice_report.html").write_text(report.text, encoding="utf-8")
        (folder / "transcript.json").write_text(json.dumps(rec.steps, ensure_ascii=False, indent=1), encoding="utf-8")
        (folder / "anchor.json").write_text(json.dumps(anchor, indent=1), encoding="utf-8")
        (folder / "summary.json").write_text(json.dumps({"scenario": name, "summary": summary, "result": result, "state": statement}, ensure_ascii=False, indent=1), encoding="utf-8")
        valid, reason = verify_audit_log(folder / "audit.jsonl")
        records = sum(1 for line in (folder / "audit.jsonl").read_text().splitlines() if line.strip())
        anchored = f"block {anchor['block']}, tx `{anchor['tx_hash'][:14]}…`, verified {anchor.get('verification', {}).get('matches')}" if anchor.get("sent") else f"not anchored: {anchor.get('note', anchor.get('detail', ''))}"
        index.append(f"| [{name}]({name}/) | {summary} | `{json.dumps(result, ensure_ascii=False)}` | {'valid' if valid else 'BROKEN: ' + reason}, {records} records | {anchored} |")
        print(f"{name}: {result} · audit {valid} ({records}) · {anchored}")
    index += ["", "Files per scenario: `audit.jsonl` (hash-chained log; check with `uv run wealth-advisor --verify-audit` and `AUDIT_LOG=<file>`), `transcript.json` (every request and response), `summary.json` (outcome and final account state), `anchor.json` (FISCO BCOS transaction and verification), `advice_report.html` (client-facing record, its SHA-256 is in the audit log)."]
    (OUT / "INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
