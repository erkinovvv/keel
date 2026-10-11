"""Web UI backend: a thin JSON API over the deterministic engine and AdvisorSession.

Run from the repo root:  uv run wealth-advisor-ui   (or: uv run uvicorn wealth_advisor.ui.server:app)

Every response that carries a number also carries its provenance: the function that computed it
and the hash of the audit record written for that computation.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from wealth_advisor.allocation import Allocation, build_allocation
from wealth_advisor.anchor import anchor_audit_log, verify_anchor
from wealth_advisor.audit import verify_audit_log
from wealth_advisor.catalog import compare_products, load_catalog
from wealth_advisor.config import Settings
from wealth_advisor.goals import GoalInput, project_goal
from wealth_advisor.permissions import PermissionDenied, PermissionTier
from wealth_advisor.profiling import QUESTIONNAIRE, InvestorProfile, profile_investor
from wealth_advisor.security import redact_pii
from wealth_advisor.session import AdvisorSession
from wealth_advisor.stress import SCENARIOS, stress_test
from wealth_advisor.ui.report import render_report
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
    goal: dict[str, Any] | None = None
    signed: bool = False
    anchors: list[dict[str, Any]] = field(default_factory=list)


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
        allocation = build_allocation(amount, requested, load_catalog(), liquidity_days=profile.liquidity_days)
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
    rows = compare_products(
        catalog, file.client["amount"], file.client["horizon_years"], profile.investor_class,
        liquidity_days=profile.liquidity_days, asset_class=asset_class or None,
    )
    hidden = [{"name": p.name, "risk_class": p.risk_class} for p in catalog if p.risk_class > profile.investor_class]
    locked = [{"name": p.name, "liquidity_days": p.liquidity_days} for p in catalog if p.risk_class <= profile.investor_class and p.liquidity_days > profile.liquidity_days]
    stamp = _record(file, "ui_products_compared", "catalog.compare_products", {"asset_class": asset_class, "count": len(rows)})
    return {"rows": [row.as_dict() for row in rows], "hidden": hidden, "locked": locked, "provenance": stamp}


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


class GoalIn(BaseModel):
    name: str = Field(default="My goal", max_length=60)
    target: float = Field(gt=0, le=1_000_000_000)
    years: int = Field(ge=1, le=50)
    monthly: float = Field(ge=0, le=10_000_000)
    inflation: float = Field(default=0.02, ge=0, lt=0.2)


@app.post("/api/goal")
def goal(body: GoalIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    _require_profile(file)
    try:
        allocation = file.session.stored_allocation("latest")
        result = project_goal(
            GoalInput(
                target=body.target, years=body.years, initial=allocation.amount, monthly=body.monthly,
                expected_return=allocation.expected_return, volatility=allocation.volatility, inflation=body.inflation,
            )
        )
    except ValueError as exc:
        raise HTTPException(409 if "allocation" in str(exc) else 422, str(exc)) from exc
    view = result.as_dict()
    file.goal = {"input": body.model_dump(), "result": view}
    stamp = _record(file, "ui_goal_projected", "goals.project_goal", {"goal": body.model_dump(), "probability": result.probability, "required_monthly": result.required_monthly})
    return {"goal": body.model_dump(), "result": view, "initial": allocation.amount, "provenance": stamp}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)


@app.post("/api/chat")
def chat(body: ChatIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    try:
        reply = file.session.send(body.message)
    except Exception as exc:  # the UI shows the failure instead of hanging
        raise HTTPException(502, f"The advisor could not answer: {exc}") from exc
    # Shown to the client so they can see what actually reached the model.
    redacted, pii_types = redact_pii(body.message)
    return {"reply": reply, "mode": file.session.settings.llm_mode, "redacted": redacted, "pii_types": list(pii_types)}


@app.post("/api/redact")
def redact(body: ChatIn) -> dict[str, Any]:
    """Preview what the model will see: the same deterministic redaction the session applies."""

    redacted, pii_types = redact_pii(body.message)
    return {"redacted": redacted, "pii_types": list(pii_types)}


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


# ---------------------------------------------------------------- execution (human-only path)


def _tier_view(file: ClientFile) -> dict[str, Any]:
    tier = file.session.tier
    return {"tier": tier.name, "level": int(tier), "kill_switch": file.session.settings.kill_switch}


def _order_view(order: dict[str, Any], products: dict[str, Any]) -> dict[str, Any]:
    product = products[order["product_id"]]
    cooling = order.get("cooling_off_until")
    return {
        **order,
        "name": product.name,
        "asset_class": product.asset_class,
        "nav": product.nav,
        "units": order["amount"] / product.nav,
        "cooling_off": bool(cooling and date.fromisoformat(cooling) > date.today()),
    }


@app.get("/api/tier")
def tier(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    return _tier_view(_file(wa_sid, response))


class ConsentIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    accepted: bool


@app.post("/api/consent")
def consent(body: ConsentIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Client signs the risk disclosure and opts this session into simulated execution."""

    file = _file(wa_sid, response)
    _require_profile(file)
    if not body.accepted:
        raise HTTPException(422, "The risk disclosure must be accepted.")
    if file.session.settings.kill_switch:
        _record(file, "consent_refused", "ui.server.consent", {"reason": "kill_switch"})
        raise HTTPException(403, "Trading is switched off for all sessions right now.")
    file.session.tier = PermissionTier.EXECUTE
    file.signed = True
    # The signature name is personal data: only its hash enters the audit log.
    signer = hashlib.sha256(body.full_name.strip().lower().encode()).hexdigest()
    stamp = _record(file, "risk_disclosure_signed", "ui.server.consent", {"signer_sha256": signer, "tier": "EXECUTE"})
    return {**_tier_view(file), "provenance": stamp}


@app.post("/api/orders/draft")
def draft_orders(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    _require_profile(file)
    try:
        orders = file.session.create_draft_orders("latest")
    except PermissionDenied as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    products = {p.id: p for p in load_catalog()}
    stamp = _record(file, "ui_orders_drafted", "session.create_draft_orders", {"order_ids": [o["order_id"] for o in orders]})
    return {
        "orders": [_order_view(o, products) for o in orders],
        "cash": file.session.state.account.cash,
        "investor_class": file.session.state.profile.investor_class,
        "provenance": stamp,
    }


class TokensIn(BaseModel):
    order_ids: list[str] = Field(min_length=1, max_length=50)


@app.post("/api/orders/tokens")
def order_tokens(body: TokensIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Issue one-time tokens to the human holding the confirm button. The LLM never sees them."""

    file = _file(wa_sid, response)
    try:
        return {"tokens": {order_id: file.session.issue_confirmation_token(order_id) for order_id in body.order_ids}}
    except PermissionDenied as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


class ConfirmIn(BaseModel):
    tokens: dict[str, str] = Field(min_length=1, max_length=50)


@app.post("/api/orders/confirm")
def confirm_orders(body: ConfirmIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    products = {p.id: p for p in load_catalog()}
    executed, failed = [], []
    for order_id, token in body.tokens.items():
        try:
            executed.append(_order_view(file.session.confirm_order(order_id, token), products))
        except (PermissionDenied, ValueError) as exc:
            failed.append({"order_id": order_id, "reason": str(exc)})
    stamp = _record(file, "ui_orders_confirmed", "session.confirm_order", {"executed": [o["order_id"] for o in executed], "failed": failed})
    return {
        "executed": executed,
        "failed": failed,
        "total": sum(o["amount"] for o in executed),
        "cash": file.session.state.account.cash,
        "investor_class": file.session.state.profile.investor_class if file.session.state.profile else None,
        "provenance": stamp,
    }


@app.post("/api/anchor")
def anchor(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Write the audit-chain head hash to Ethereum Sepolia (dry run when no wallet is configured)."""

    file = _file(wa_sid, response)
    path = Path(file.session.settings.audit_log)
    try:
        receipt = anchor_audit_log(path)
    except Exception as exc:  # network and RPC failures must not break the advice flow
        _record(file, "anchor_failed", "anchor.anchor_audit_log", {"error": type(exc).__name__, "message": str(exc)[:200]})
        raise HTTPException(502, f"Could not anchor on Sepolia: {exc}") from exc
    view = receipt.as_dict()
    file.anchors.append(view)
    _record(file, "audit_anchored" if receipt.sent else "audit_anchor_dry_run", "anchor.anchor_audit_log", view)
    return view


@app.get("/api/anchor/verify")
def anchor_verify(tx: str, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    if not tx.startswith("0x") or len(tx) != 66:
        raise HTTPException(422, "Not a transaction hash.")
    try:
        return verify_anchor(tx, Path(file.session.settings.audit_log))
    except Exception as exc:
        raise HTTPException(502, f"Could not verify: {exc}") from exc


@app.get("/api/anchors")
def anchors(response: Response, wa_sid: str | None = Cookie(default=None)) -> list[dict[str, Any]]:
    return _file(wa_sid, response).anchors


@app.get("/report", response_class=HTMLResponse)
def advice_report(response: Response, wa_sid: str | None = Cookie(default=None)) -> HTMLResponse:
    """Printable suitability record; its fingerprint is written to the audit chain."""

    file = _file(wa_sid, response)
    profile = file.session.state.profile
    if profile is None:
        return HTMLResponse("<p style='font-family:sans-serif;padding:40px'>Complete the risk questionnaire first, then open the report again.</p>", status_code=409)
    try:
        allocation = file.session.stored_allocation("latest")
    except ValueError:
        allocation = None
    stress_results = [stress_test(allocation, key, max_tolerable_loss=file.client.get("max_loss", 0.2)) for key in SCENARIOS] if allocation else []
    path = Path(file.session.settings.audit_log)
    valid, _ = verify_audit_log(path)
    count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) if path.exists() else 0
    html, digest = render_report(
        profile=profile, client=file.client, allocation=allocation, stress=stress_results, goal=file.goal,
        products={p.id: p for p in load_catalog()}, audit_valid=valid, audit_records=count,
        signed=file.signed, model_mode=file.session.settings.llm_mode,
    )
    _record(file, "advice_report_issued", "ui.report.render_report", {"report_sha256": digest})
    return HTMLResponse(html)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run("wealth_advisor.ui.server:app", host="127.0.0.1", port=8600, reload=False)
