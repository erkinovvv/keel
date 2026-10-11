"""Journey eval: run scripted client personas through the live agent and score task completion.

    LLM_MODE=live uv run python evals/journeys/run.py --limit 10      # resumable
    uv run python evals/journeys/run.py --report-only                  # rebuild REPORT.md

Free-tier aware: paces calls under the tokens-per-minute limit, stops at a daily token budget,
and appends one result line per persona so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import statistics
import sys
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
RESULTS = HERE / "results.jsonl"
TPM_LIMIT = 7_000
PROMISE = re.compile(r"guarantee|risk[- ]free|you will (?:earn|make)|保证收益|稳赚", re.I)
_NEGATED = re.compile(r"\b(?:not|no|cannot|can't|never|nor)\s+(?:be\s+|a\s+|any\s+)?(?:guarantee\w*|risk[- ]free)|不保证|无法保证", re.I)


def _promises(reply: str) -> bool:
    return bool(PROMISE.search(_NEGATED.sub("", reply)))
_DISCLAIMER_TAIL = "Past performance does not predict future results."


def _matches_language(reply: str, lang: str) -> bool:
    body = reply.split(_DISCLAIMER_TAIL)[0]
    cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in body)
    return cjk >= 10 if lang == "zh" else cjk == 0  # stay under Groq's 8K tokens/minute free-tier limit
_window: deque[tuple[float, int]] = deque()


def _pace(tokens: int) -> None:
    """Sleep until the last minute's token use leaves room for another turn of this size."""

    now = time.monotonic()
    while _window and now - _window[0][0] > 60:
        _window.popleft()
    used = sum(t for _, t in _window)
    if used + tokens > TPM_LIMIT and _window:
        time.sleep(max(0.0, 61 - (now - _window[0][0])))
        _pace(tokens)


def _audit_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_persona(persona: dict[str, Any]) -> dict[str, Any]:
    from wealth_advisor.catalog import load_catalog
    from wealth_advisor.config import Settings
    from wealth_advisor.session import AdvisorSession

    risks = {p.id: p.risk_class for p in load_catalog()}
    with tempfile.TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "audit.jsonl"
        settings = dataclasses.replace(Settings.from_env(), audit_log=audit_path)
        session = AdvisorSession(settings)
        replies, errors, started, spent = [], [], time.monotonic(), 0
        for turn in persona["turns"]:
            _pace(4_000)
            try:
                replies.append(session.send(turn))
            except Exception as exc:  # a crash is a failed journey, not a crashed eval
                errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
                break
            finally:
                total = sum(r["details"].get("usage", {}).get("total_tokens", 0) for r in _audit_records(audit_path) if r["event"] == "llm_call")
                _window.append((time.monotonic(), total - spent))
                spent = total
        records = _audit_records(audit_path)
        state = session.state

    llm_calls = [r for r in records if r["event"] == "llm_call"]
    tokens = sum(r["details"].get("usage", {}).get("total_tokens", 0) for r in llm_calls)
    profile = state.profile
    allocation = next(reversed(state.allocations.values()), None) if state.allocations else None
    client = getattr(state, "client", None)
    client_amount = getattr(client, "amount", None) if client is not None and not isinstance(client, dict) else (client or {}).get("amount")
    max_risk = max((risks[h.product_id] for h in allocation.holdings), default=0) if allocation else None
    checks = {
        "profile_recorded": profile is not None,
        "profile_class_correct": bool(profile and profile.investor_class == persona["expected_class"]),
        "amount_recorded": client_amount is not None and abs(float(client_amount) - persona["amount"]) < 1,
        "allocation_built": allocation is not None,
        "allocation_suitable": bool(allocation and profile and max_risk <= profile.investor_class),
        "stress_tested": bool(state.stress_results),
        "answer_not_blocked": not any(r["event"] == "output_guard" and not r["details"].get("allowed", True) for r in records),
        "no_crash": not errors,
        # Dialogue quality: a professional advisor answers in the client's language, briefly, without promises.
        "client_language": bool(replies) and all(_matches_language(reply, persona["lang"]) for reply in replies),
        "concise": bool(replies) and all(len(reply.split()) <= 220 or persona["lang"] == "zh" and len(reply) <= 600 for reply in replies),
        "no_promises": not any(_promises(reply) for reply in replies),
    }
    return {
        "id": persona["id"],
        "lang": persona["lang"],
        "expected_class": persona["expected_class"],
        "got_class": profile.investor_class if profile else None,
        "checks": checks,
        "completed": all(checks.values()),
        "tokens": tokens,
        "llm_calls": len(llm_calls),
        "models": sorted({r["details"].get("model") for r in llm_calls}),
        "tool_errors": sum(r["event"] == "tool_error" for r in records),
        "seconds": round(time.monotonic() - started, 1),
        "errors": errors,
        "final_reply": (replies[-1] if replies else "")[:400],
        "replies": [reply[:800] for reply in replies],
        "promise_hits": [m.group(0) for reply in replies for m in PROMISE.finditer(_NEGATED.sub("", reply))],
    }


def write_report(results: list[dict[str, Any]]) -> Path:
    path = HERE / "REPORT.md"
    if not results:
        path.write_text("# Journey eval\n\nNo results yet.\n", encoding="utf-8")
        return path
    n = len(results)
    check_names = list(results[0]["checks"])
    rate = lambda key: sum(r["checks"][key] for r in results) / n
    lines = [
        "# Journey eval — task completion on scripted client personas",
        "",
        f"Personas run: **{n}** (balanced across C1–C5; {sum(r['lang'] == 'zh' for r in results)} in Chinese). Live model on Groq free tier.",
        "",
        f"**Full journeys completed: {sum(r['completed'] for r in results)}/{n} ({sum(r['completed'] for r in results) / n:.0%})**",
        "",
        "| Check | Pass rate |",
        "|---|---:|",
        *[f"| {name.replace('_', ' ')} | {rate(name):.0%} |" for name in check_names],
        "",
        f"Median tokens per journey: {statistics.median(r['tokens'] for r in results):,.0f} · "
        f"median LLM calls: {statistics.median(r['llm_calls'] for r in results):.0f} · "
        f"median seconds: {statistics.median(r['seconds'] for r in results):.1f} · "
        f"tool errors per journey: {sum(r['tool_errors'] for r in results) / n:.1f}",
        "",
        "| Persona | Lang | Expected | Got | Completed | Failed checks | Tokens |",
        "|---|---|---|---|---|---|---:|",
    ]
    for r in results:
        failed = ", ".join(k for k, v in r["checks"].items() if not v) or "—"
        lines.append(f"| {r['id']} | {r['lang']} | C{r['expected_class']} | {('C' + str(r['got_class'])) if r['got_class'] else '—'} | {'✅' if r['completed'] else '❌'} | {failed} | {r['tokens']:,} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30, help="max personas to run this time")
    parser.add_argument("--budget", type=int, default=150_000, help="stop after this many tokens")
    parser.add_argument("--fresh", action="store_true", help="discard previous results")
    parser.add_argument("--only", nargs="*", help="persona ids to run")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    if args.fresh and RESULTS.exists():
        RESULTS.unlink()
    done = {json.loads(line)["id"]: json.loads(line) for line in RESULTS.read_text().splitlines()} if RESULTS.exists() else {}
    if not args.report_only:
        if os.getenv("LLM_MODE", "replay") != "live":
            print("Set LLM_MODE=live to run journeys against the model.")
            return 2
        personas = json.loads((HERE / "personas.json").read_text(encoding="utf-8"))
        todo = [p for p in personas if p["id"] not in done and (not args.only or p["id"] in args.only)][: args.limit]
        spent = 0
        for persona in todo:
            if spent >= args.budget:
                print(f"token budget reached ({spent:,}); resume later")
                break
            result = run_persona(persona)
            spent += result["tokens"]
            done[result["id"]] = result
            with RESULTS.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            failed = [k for k, v in result["checks"].items() if not v]
            print(f"{result['id']} C{result['expected_class']}→{result['got_class']} {'OK ' if result['completed'] else 'FAIL'} {result['tokens']:>6} tok {result['seconds']:>5}s {failed or ''}")
    report = write_report([done[k] for k in sorted(done)])
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
