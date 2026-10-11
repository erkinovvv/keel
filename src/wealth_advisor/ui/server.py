"""Web UI backend: a thin JSON API over the deterministic engine and AdvisorSession.

Run from the repo root:  uv run wealth-advisor-ui   (or: uv run uvicorn wealth_advisor.ui.server:app)

Every response that carries a number also carries its provenance: the function that computed it
and the hash of the audit record written for that computation.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from wealth_advisor.allocation import Allocation, build_allocation
from wealth_advisor.audit import verify_audit_log
from wealth_advisor.catalog import compare_products, load_catalog
from wealth_advisor.config import Settings
from wealth_advisor.profiling import QUESTIONNAIRE, InvestorProfile, profile_investor
from wealth_advisor.session import AdvisorSession
from wealth_advisor.stress import SCENARIOS, stress_test
from wealth_advisor.ui.labels import CLASS_NAMES, FLAG_LABELS, explain_reason, humanize, question_label

STATIC = Path(__file__).parent / "static"
SCENARIO_NAMES = {
    "2008_gfc": "2008 global financial crisis",
    "2020_covid": "2020 pandemic crash",
    "2022_rate_shock": "2022 rate shock",
}

app = FastAPI(title="Wealth Advisor Agent", docs_url="/api/docs")


@dataclass
class ClientFile:
    """Per-browser state: the shared AdvisorSession plus UI-only client inputs."""

    session: AdvisorSession
    client: dict[str, Any] = field(default_factory=dict)
    allocation_count: int = 0


_FILES: dict[str, ClientFile] = {}


def _file(sid: str | None, response: Response) -> ClientFile:
    if sid and sid in _FILES:
        return _FILES[sid]
    sid = secrets.token_urlsafe(16)
    _FILES[sid] = ClientFile(session=AdvisorSession(Settings.from_env()))
    response.set_cookie("wa_sid", sid, httponly=True, samesite="strict")
    return _FILES[sid]


def _record(file: ClientFile, event: str, source: str, details: dict[str, Any]) -> dict[str, str]:
    """Write an audit record and return the provenance stamp the UI shows next to numbers."""

    record = file.session.audit.append(event, {"source": source, **details})
    return {"source": source, "audit_hash": record["hash"], "timestamp": record["timestamp"]}


def _profile_view(profile: InvestorProfile) -> dict[str, Any]:
    return {
        "investor_class": profile.investor_class,
        "class_name": CLASS_NAMES[profile.investor_class],
        "capacity_class": profile.capacity_class,
        "tolerance_class": profile.tolerance_class,
        "capacity_score": profile.capacity_score,
        "tolerance_score": profile.tolerance_score,
        "expires_on": profile.expires_on.isoformat(),
        "reasons": [{"code": code, "text": explain_reason(code)} for code in profile.reason_codes],
        "flags": [{"code": flag, "text": FLAG_LABELS.get(flag, flag)} for flag in profile.vulnerability_flags],
    }


def _allocation_view(allocation: Allocation) -> dict[str, Any]:
    products = {p.id: p for p in load_catalog()}
    return {
        "investor_class": allocation.investor_class,
        "amount": allocation.amount,
        "expected_return": allocation.expected_return,
        "volatility": allocation.volatility,
        "fee": allocation.fee,
        "var_95_1y": allocation.var_95_1y,
        "by_asset_class": {k: v for k, v in allocation.strategic_weights.items() if v > 0},
        "holdings": [
            {
                "product_id": h.product_id,
                "name": products[h.product_id].name,
                "asset_class": h.asset_class,
                "risk_class": products[h.product_id].risk_class,
                "weight": h.weight,
                "amount": h.amount,
                "reasons": [explain_reason(code) for code in h.reason_codes],
            }
            for h in allocation.holdings
        ],
    }


def _require_profile(file: ClientFile) -> InvestorProfile:
    profile = file.session.state.profile
    if profile is None:
        raise HTTPException(409, "Complete the risk questionnaire first.")
    return profile


# ---------------------------------------------------------------- API


@app.get("/api/questionnaire")
def questionnaire() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "question": question_label(key),
            "domain": spec["domain"],
            "options": [{"key": option, "label": humanize(option)} for option in spec["options"]],
        }
        for key, spec in QUESTIONNAIRE.items()
    ]


class ProfileIn(BaseModel):
    answers: dict[str, str]
    age: int = Field(ge=18, le=120)
    borrowed_money: bool = False
    amount: float = Field(gt=0, le=100_000_000)
    horizon_years: int = Field(ge=1, le=50)
    max_loss: float = Field(gt=0, le=1)


@app.post("/api/profile")
def assess_profile(body: ProfileIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    try:
        profile = profile_investor(body.answers, age=body.age, borrowed_money=body.borrowed_money)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    file.session.state.profile = profile
    file.client = {"amount": body.amount, "horizon_years": body.horizon_years, "max_loss": body.max_loss, "age": body.age}
    stamp = _record(file, "ui_profile_assessed", "profiling.profile_investor", {"profile": profile.as_dict()})
    return {"profile": _profile_view(profile), "client": file.client, "provenance": stamp}


class AllocationIn(BaseModel):
    amount: float | None = Field(default=None, gt=0, le=100_000_000)
    investor_class: int | None = Field(default=None, ge=1, le=5)


@app.post("/api/allocation")
def allocate(body: AllocationIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    profile = _require_profile(file)
    requested = body.investor_class or profile.investor_class
    if requested > profile.investor_class:
        # Suitability is enforced on the server: the UI can only ever step risk down.
        _record(file, "suitability_block", "ui.server.allocate", {"requested": requested, "allowed": profile.investor_class})
        raise HTTPException(403, f"C{requested} exceeds the assessed class C{profile.investor_class}.")
    amount = body.amount or file.client["amount"]
    try:
        allocation = build_allocation(amount, requested, load_catalog())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    file.allocation_count += 1
    allocation_id = f"ui-{file.allocation_count}"
    file.session.state.allocations[allocation_id] = allocation
    stamp = _record(file, "ui_allocation_built", "allocation.build_allocation", {"allocation_id": allocation_id, "allocation": allocation.as_dict()})
    return {"allocation_id": allocation_id, "allocation": _allocation_view(allocation), "provenance": stamp}


@app.get("/api/compare")
def compare(response: Response, asset_class: str | None = None, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    profile = _require_profile(file)
    catalog = load_catalog()
    rows = compare_products(catalog, file.client["amount"], file.client["horizon_years"], profile.investor_class, asset_class=asset_class or None)
    hidden = [{"name": p.name, "risk_class": p.risk_class} for p in catalog if p.risk_class > profile.investor_class]
    stamp = _record(file, "ui_products_compared", "catalog.compare_products", {"asset_class": asset_class, "count": len(rows)})
    return {"rows": [row.as_dict() for row in rows], "hidden": hidden, "provenance": stamp}


@app.get("/api/stress")
def stress(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    _require_profile(file)
    try:
        allocation = file.session.stored_allocation("latest")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    results = [stress_test(allocation, key, max_tolerable_loss=file.client["max_loss"]) for key in SCENARIOS]
    stamp = _record(file, "ui_stress_tested", "stress.stress_test", {"results": [r.as_dict() for r in results]})
    return {
        "max_loss": file.client["max_loss"],
        "scenarios": [
            {"key": r.scenario, "name": SCENARIO_NAMES.get(r.scenario, r.scenario), "loss": r.loss_percent, "loss_amount": r.loss_amount, "breach": r.mismatch}
            for r in results
        ],
        "provenance": stamp,
    }


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)


@app.post("/api/chat")
def chat(body: ChatIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    try:
        reply = file.session.send(body.message)
    except Exception as exc:  # the UI shows the failure instead of hanging
        raise HTTPException(502, f"The advisor could not answer: {exc}") from exc
    return {"reply": reply, "mode": file.session.settings.llm_mode}


@app.get("/api/audit")
def audit(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    path = Path(file.session.settings.audit_log)
    valid, reason = verify_audit_log(path)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    return {
        "valid": valid,
        "reason": reason,
        "total": len(records),
        "records": [
            {"timestamp": r["timestamp"], "event": r["event"], "source": r.get("details", {}).get("source"), "hash": r["hash"], "prev_hash": r.get("prev_hash")}
            for r in reversed(records[-60:])
        ],
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run("wealth_advisor.ui.server:app", host="127.0.0.1", port=8600, reload=False)
