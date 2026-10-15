"""Web UI backend: a thin JSON API over the deterministic engine and AdvisorSession.

Run from the repo root:  uv run wealth-advisor-ui   (or: uv run uvicorn wealth_advisor.ui.server:app)

Every response that carries a number also carries its provenance: the function that computed it
and the hash of the audit record written for that computation.
"""

from __future__ import annotations

import dataclasses
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import zlib
from contextvars import ContextVar
from datetime import date
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from wealth_advisor.account import SimulatedAccount, SimulatedOrder
from wealth_advisor.allocation import Allocation, Holding, build_allocation
from wealth_advisor.anchor import anchor_audit_log, network as anchor_network, verify_anchor
from wealth_advisor.audit import AuditLogger, verify_audit_log
from wealth_advisor.catalog import compare_products, load_catalog
from wealth_advisor.config import Settings
from wealth_advisor.goals import GoalInput, project_goal
from wealth_advisor.permissions import PermissionDenied, PermissionTier
from wealth_advisor.profiling import QUESTIONNAIRE, InvestorProfile, profile_investor
from wealth_advisor.rehearsal import apply_outcome, evaluate, load_scenario, portfolio_path
from wealth_advisor.monitoring import EVENTS, check_live_market, check_market
from wealth_advisor.security import RateLimiter, redact_pii
from wealth_advisor.session import AdvisorSession, ClientFacts
from wealth_advisor.stress import SCENARIOS, StressResult, stress_test
from wealth_advisor.ontology import (
    AdvisoryStage,
    ArtifactStatus,
    AuditReference,
    ClientConsent,
    GoalRecord,
    OrderProposal,
    Recommendation,
    canonical_hash,
    now_utc,
)
from wealth_advisor.ui.report import render_report
from wealth_advisor.ui.labels import LANG, class_name, lang, explain_reason, flag_label, humanize, question_label

STATIC = Path(__file__).parent / "static"
SCENARIO_NAMES = {
    "2008_gfc": "2008 global financial crisis",
    "2020_covid": "2020 pandemic crash",
    "2022_rate_shock": "2022 rate shock",
}
ANCHOR_NOTE = "Audit anchoring is configured for Sepolia. A transaction is sent only when a funded SEPOLIA_PRIVATE_KEY is configured; otherwise the audit chain remains local to this session."

app = FastAPI(title="Keel", docs_url="/api/docs")


CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@app.middleware("http")
async def request_context(request, call_next):
    """Per-request language and client address, plus security headers on every response."""

    LANG.set("zh" if request.cookies.get("wa_lang") == "zh" else "en")
    CLIENT_IP.set(request.client.host if request.client else "unknown")
    sid = request.cookies.get("wa_sid")
    if sid and sid not in _FILES:
        payload = _open_state(request.cookies.get(_STATE_COOKIE, ""), sid)
        if payload is not None:
            _FILES[sid] = _restore_file(sid, payload)
    response = await call_next(request)
    if sid and sid in _FILES:
        token = _seal_state(_FILES[sid], sid)
        if len(token) <= _STATE_COOKIE_MAX:
            response.set_cookie(_STATE_COOKIE, token, httponly=True, secure=_secure_cookies(), samesite="strict")
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """Liveness and a summary of what this instance is running with."""

    from importlib.metadata import version
    settings = Settings.from_env()

    return {
        "status": "ok",
        "version": version("wealth-advisor"),
        "llm_mode": settings.llm_mode,
        "catalog": "cn" if os.getenv("WEALTH_ADVISOR_CATALOG", "").lower() == "cn" else "mock",
        "products": len(load_catalog()),
        "audit_chain_valid": True,
        "audit_scope": "per_session",
        "anchor_network": anchor_network(),
        "anchor_note": ANCHOR_NOTE,
        "active_sessions": len(_FILES),
    }


@dataclass
class ClientFile:
    """Per-browser state: the shared AdvisorSession plus UI-only client inputs."""

    session: AdvisorSession
    allocation_count: int = 0
    allocation_provenance: dict[str, dict[str, str]] = field(default_factory=dict)
    goal: dict[str, Any] | None = None
    signed: bool = False
    anchors: list[dict[str, Any]] = field(default_factory=list)
    rehearsals: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    last_seen: float = field(default_factory=time.monotonic)


SESSION_IDLE_SECONDS = int(os.getenv("SESSION_IDLE_SECONDS", "7200"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "500"))
NEW_SESSIONS_PER_IP = int(os.getenv("NEW_SESSIONS_PER_IP", "30"))  # per 10 minutes
CLIENT_IP: ContextVar[str] = ContextVar("client_ip", default="unknown")
_NEW_SESSION_TIMES: dict[str, list[float]] = {}
_CHAT_LIMITERS: dict[str, RateLimiter] = {}


def _evict_sessions(now: float) -> None:
    """Drop idle sessions and keep the store bounded (oldest first)."""

    for sid in [k for k, f in _FILES.items() if now - f.last_seen > SESSION_IDLE_SECONDS]:
        del _FILES[sid]
    while len(_FILES) >= MAX_SESSIONS:
        del _FILES[min(_FILES, key=lambda k: _FILES[k].last_seen)]


_FILES: dict[str, ClientFile] = {}
_STATE_COOKIE = "wa_state"
_STATE_COOKIE_MAX = 3800
_STATE_COOKIE_SECRET = os.getenv("STATE_COOKIE_SECRET") or secrets.token_bytes(32).hex()


def _secure_cookies() -> bool:
    return os.getenv("VERCEL") == "1" or os.getenv("ENVIRONMENT", "").lower() == "production"


def _session_audit_path(settings: Settings, sid: str) -> Path:
    digest = hashlib.sha256(sid.encode()).hexdigest()[:24]
    base = Path(settings.audit_log)
    return base.with_name(f"{base.stem}-{digest}{base.suffix or '.jsonl'}")


def _bind_session_audit(session: AdvisorSession, sid: str) -> None:
    """Give each browser session an independent audit chain and all components the same logger."""

    path = _session_audit_path(session.settings, sid)
    session.settings = dataclasses.replace(session.settings, audit_log=path)
    audit = AuditLogger(path, session_id=hashlib.sha256(sid.encode()).hexdigest()[:12])
    session.audit = audit
    session.agent.audit = audit
    session.agent.llm.audit = audit
    session.dispatcher.audit = audit
    session.prompt_guard.audit = audit


def _state_cookie_key() -> bytes:
    return _STATE_COOKIE_SECRET.encode("utf-8")


def _seal_state(file: ClientFile, sid: str) -> str:
    state = file.session.state
    payload = {
        "sid": sid,
        "client": state.client.as_dict(),
        "profile": state.profile.as_dict() if state.profile else None,
        "allocations": {key: allocation.as_dict() for key, allocation in state.allocations.items()},
        "stress_results": {key: result.as_dict() for key, result in state.stress_results.items()},
        "draft_orders": {key: order.as_dict() for key, order in state.draft_orders.items()},
        "account": {
            "cash": state.account.cash,
            "holdings": state.account.holdings,
            "orders": {key: order.as_dict() for key, order in state.account.orders.items()},
        },
        "allocation_count": file.allocation_count,
        "allocation_provenance": file.allocation_provenance,
        "goal": state.goal or file.goal,
        "signed": file.signed,
        "rehearsals": file.rehearsals,
        "alerts": file.alerts,
        "anchors": file.anchors,
        "stage": state.stage.value,
        "facts_version": state.facts_version,
        "profile_version": state.profile_version,
        "profile_facts_version": state.profile_facts_version,
        "profile_invalidated": state.profile_invalidated,
        "goal_record": state.goal_record.as_dict() if state.goal_record else None,
        "recommendation": state.recommendation.as_dict() if state.recommendation else None,
        "consent": state.consent.as_dict() if state.consent else None,
        "order_proposals": {key: value.as_dict() for key, value in state.order_proposals.items()},
    }
    encoded = base64.urlsafe_b64encode(zlib.compress(json.dumps(payload, separators=(",", ":")).encode(), 9)).decode()
    signature = hmac.new(_state_cookie_key(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _open_state(token: str, sid: str) -> dict[str, Any] | None:
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(_state_cookie_key(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(zlib.decompress(base64.urlsafe_b64decode(encoded)).decode())
        return payload if payload.get("sid") == sid else None
    except (ValueError, TypeError, OSError, zlib.error, json.JSONDecodeError):
        return None


def _restore_profile(raw: dict[str, Any] | None) -> InvestorProfile | None:
    if not raw:
        return None
    return InvestorProfile(
        investor_class=raw["investor_class"], capacity_score=raw["capacity_score"], tolerance_score=raw["tolerance_score"],
        capacity_class=raw["capacity_class"], tolerance_class=raw["tolerance_class"], liquidity_days=raw["liquidity_days"],
        reason_codes=tuple(raw["reason_codes"]), vulnerability_flags=tuple(raw["vulnerability_flags"]),
        expires_on=date.fromisoformat(raw["expires_on"]),
    )


def _restore_allocation(raw: dict[str, Any]) -> Allocation:
    return Allocation(
        investor_class=raw["investor_class"], amount=raw["amount"],
        holdings=tuple(Holding(h["product_id"], h["asset_class"], h["weight"], h["amount"], tuple(h["reason_codes"])) for h in raw["holdings"]),
        expected_return=raw["expected_return"], volatility=raw["volatility"], fee=raw["fee"],
        var_95_1y_parametric=raw["var_95_1y_parametric"], strategic_weights=raw["strategic_weights"],
        volatility_band=tuple(raw["volatility_band"]), reason_codes=tuple(raw.get("reason_codes", ())),
        stress_limit_before=raw.get("stress_limit_before"), stress_limit_after=raw.get("stress_limit_after"),
    )


def _restore_order(raw: dict[str, Any]) -> SimulatedOrder:
    return SimulatedOrder(
        order_id=raw["order_id"], product_id=raw["product_id"], amount=raw["amount"], risk_class=raw["risk_class"],
        status=raw["status"], created_on=date.fromisoformat(raw["created_on"]),
        settles_on=date.fromisoformat(raw["settles_on"]) if raw.get("settles_on") else None,
        cooling_off_until=date.fromisoformat(raw["cooling_off_until"]) if raw.get("cooling_off_until") else None,
        units=raw.get("units"), price=raw.get("price"),
    )


def _restore_recommendation(raw: dict[str, Any] | None) -> Recommendation | None:
    if not raw:
        return None
    audit = raw.get("audit_reference")
    return Recommendation(
        recommendation_id=raw["recommendation_id"], profile_id=raw["profile_id"], goal_id=raw.get("goal_id"),
        allocation_id=raw["allocation_id"], profile_version=raw["profile_version"], goal_version=raw.get("goal_version"),
        catalog_version=raw["catalog_version"], calculation_version=raw["calculation_version"], created_at=raw["created_at"],
        status=raw["status"], expected_return=raw["expected_return"], volatility=raw["volatility"], fee=raw["fee"],
        var_95=raw["var_95"], stress_summary=raw.get("stress_summary", {}), reason_codes=tuple(raw.get("reason_codes", ())),
        rejected_alternatives=tuple(raw.get("rejected_alternatives", ())), stale_reasons=tuple(raw.get("stale_reasons", ())),
        audit_reference=AuditReference(**audit) if audit else None,
    )


def _restore_consent(raw: dict[str, Any] | None) -> ClientConsent | None:
    if not raw:
        return None
    audit = raw.get("audit_reference")
    return ClientConsent(
        consent_id=raw["consent_id"], recommendation_id=raw["recommendation_id"],
        exact_recommendation_hash=raw["exact_recommendation_hash"], risk_disclosure_hash=raw["risk_disclosure_hash"],
        client_confirmed_at=raw.get("client_confirmed_at"), confirmation_channel=raw["confirmation_channel"],
        status=raw["status"], audit_reference=AuditReference(**audit) if audit else None,
    )


def _restore_order_proposal(raw: dict[str, Any]) -> OrderProposal:
    audit = raw.get("audit_reference")
    return OrderProposal(
        order_id=raw["order_id"], recommendation_id=raw["recommendation_id"], product_id=raw["product_id"],
        amount_cny=raw["amount_cny"], risk_class=raw["risk_class"], suitability_result=raw.get("suitability_result", {}),
        created_at=raw["created_at"], status=raw["status"], order_summary_hash=raw["order_summary_hash"],
        audit_reference=AuditReference(**audit) if audit else None,
    )


def _restore_file(sid: str, payload: dict[str, Any]) -> ClientFile:
    session = AdvisorSession(Settings.from_env())
    _bind_session_audit(session, sid)
    session.state.client = ClientFacts(**payload.get("client", {}))
    session.state.profile = _restore_profile(payload.get("profile"))
    session.state.allocations = {key: _restore_allocation(value) for key, value in payload.get("allocations", {}).items()}
    session.state.stress_results = {key: StressResult(**value) for key, value in payload.get("stress_results", {}).items()}
    account_data = payload.get("account", {})
    session.state.account = SimulatedAccount(
        cash=account_data.get("cash", session.settings.simulated_cash),
        holdings=account_data.get("holdings", {}),
        orders={key: _restore_order(value) for key, value in account_data.get("orders", {}).items()},
    )
    session.state.draft_orders = {
        key: _restore_order(value) for key, value in payload.get("draft_orders", {}).items()
    }
    session.state.goal = payload.get("goal")
    if payload.get("goal_record"):
        session.state.goal_record = GoalRecord(**payload["goal_record"])
    session.state.recommendation = _restore_recommendation(payload.get("recommendation"))
    session.state.consent = _restore_consent(payload.get("consent"))
    session.state.order_proposals = {key: _restore_order_proposal(value) for key, value in payload.get("order_proposals", {}).items()}
    if payload.get("stage"):
        session.state.stage = AdvisoryStage(payload["stage"])
    session.state.facts_version = payload.get("facts_version", session.state.facts_version)
    session.state.profile_version = payload.get("profile_version")
    session.state.profile_facts_version = payload.get("profile_facts_version")
    session.state.profile_invalidated = bool(payload.get("profile_invalidated", False))
    return ClientFile(
        session=session, allocation_count=payload.get("allocation_count", len(session.state.allocations)),
        allocation_provenance=payload.get("allocation_provenance", {}), goal=payload.get("goal"), signed=payload.get("signed", False),
        rehearsals=payload.get("rehearsals", []), alerts=payload.get("alerts", []), anchors=payload.get("anchors", []),
    )


def _file(sid: str | None, response: Response, state_token: str | None = None) -> ClientFile:
    now = time.monotonic()
    if sid and sid in _FILES:
        _FILES[sid].last_seen = now
        return _FILES[sid]
    if sid and state_token:
        payload = _open_state(state_token, sid)
        if payload is not None:
            restored = _restore_file(sid, payload)
            restored.last_seen = now
            _FILES[sid] = restored
            return restored
    ip = CLIENT_IP.get()
    recent = [t for t in _NEW_SESSION_TIMES.get(ip, []) if now - t < 600]
    if len(recent) >= NEW_SESSIONS_PER_IP:
        raise HTTPException(429, "Too many new sessions from this address; try again in a few minutes.")
    _NEW_SESSION_TIMES[ip] = [*recent, now]
    _evict_sessions(now)
    sid = secrets.token_urlsafe(16)
    session = AdvisorSession(Settings.from_env())
    _bind_session_audit(session, sid)
    _FILES[sid] = ClientFile(session=session)
    response.set_cookie("wa_sid", sid, httponly=True, secure=_secure_cookies(), samesite="strict")
    response.set_cookie(_STATE_COOKIE, _seal_state(_FILES[sid], sid), httponly=True, secure=_secure_cookies(), samesite="strict")
    return _FILES[sid]


def _client(file: ClientFile) -> dict[str, Any]:
    """Client facts live in the shared session state, so chat and UI always agree."""

    return file.session.state.client.as_dict()


def _require_client(file: ClientFile, *keys: str) -> dict[str, Any]:
    client = _client(file)
    missing = [key for key in keys if client.get(key) is None]
    if missing:
        raise HTTPException(409, f"Tell the advisor your {', '.join(k.replace('_', ' ') for k in missing)} first.")
    return client


def _answers_from_profile(profile: InvestorProfile) -> dict[str, str]:
    """Recover questionnaire answers from reason codes so the form mirrors a chat-built profile."""

    answers: dict[str, str] = {}
    for question in sorted(QUESTIONNAIRE, key=len, reverse=True):
        prefix = question.upper() + "_"
        for code in profile.reason_codes:
            if code.startswith(prefix) and question not in answers:
                option = code[len(prefix):].lower()
                if option in QUESTIONNAIRE[question]["options"]:
                    answers[question] = option
    return answers


def _allocation_provenance(file: ClientFile, allocation_id: str) -> dict[str, str]:
    if allocation_id in file.allocation_provenance:
        return file.allocation_provenance[allocation_id]
    path = Path(file.session.settings.audit_log)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    for record in reversed(records):  # built by the agent in chat: cite the tool call record
        if record.get("event") == "tool_call" and record.get("details", {}).get("tool") == "build_allocation":
            return {"source": "agent tool build_allocation", "audit_hash": record["hash"], "timestamp": record["timestamp"]}
    return {"source": "allocation.build_allocation", "audit_hash": "0" * 64, "timestamp": ""}


def _ui_state(file: ClientFile) -> dict[str, Any]:
    state = file.session.state
    allocation_id = state.latest_allocation_id
    return {
        "profile": _profile_view(state.profile) if state.profile else None,
        "answers": _answers_from_profile(state.profile) if state.profile else {},
        "client": _client(file),
        "allocation_id": allocation_id,
        "allocation": _allocation_view(state.allocations[allocation_id]) if allocation_id else None,
        "allocation_provenance": _allocation_provenance(file, allocation_id) if allocation_id else None,
        "tier": _tier_view(file),
        "goal": state.goal or file.goal,
        "stage": state.stage.value,
        "profile_version": state.profile_version,
        "recommendation": state.recommendation.as_dict() if state.recommendation else None,
        "recommendation_hash": state.recommendation.fingerprint if state.recommendation else None,
        "stale_reasons": list(state.recommendation.stale_reasons) if state.recommendation else [],
        "consent": state.consent.as_dict() if state.consent else None,
    }


def _record(file: ClientFile, event: str, source: str, details: dict[str, Any]) -> dict[str, str]:
    """Write an audit record and return the provenance stamp the UI shows next to numbers."""

    record = file.session.audit.append(event, {"source": source, **details})
    return {"source": source, "audit_hash": record["hash"], "timestamp": record["timestamp"]}


def _profile_view(profile: InvestorProfile) -> dict[str, Any]:
    return {
        "investor_class": profile.investor_class,
        "class_name": class_name(profile.investor_class),
        "capacity_class": profile.capacity_class,
        "tolerance_class": profile.tolerance_class,
        "capacity_score": profile.capacity_score,
        "tolerance_score": profile.tolerance_score,
        "expires_on": profile.expires_on.isoformat(),
        "reasons": [{"code": code, "text": explain_reason(code)} for code in profile.reason_codes],
        "flags": [{"code": flag, "text": flag_label(flag)} for flag in profile.vulnerability_flags],
    }


@lru_cache(maxsize=1)
def _fund_meta() -> dict[str, Any]:
    """Codes, Chinese names and sources for the real-fund catalog (empty for the mock catalog)."""

    path = Path(__file__).parents[1] / "data" / "products_cn_meta.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"funds": {}}


def _product_name(product: Any) -> str:
    meta = _fund_meta()["funds"].get(product.id)
    if meta and lang() == "zh":
        return f"{meta['name_zh']}（{meta['code']}）"
    if lang() == "zh" and getattr(product, "name_zh", None):
        return product.name_zh
    return product.name


def _fixed_income_view(product: Any) -> dict[str, Any]:
    """Term, rate and issuer for deposits and savings bonds; empty for funds."""

    if getattr(product, "kind", "fund") == "fund":
        return {"kind": "fund"}
    return {
        "kind": product.kind,
        "term_months": product.term_months,
        "rate": product.expected_return,
        "issuer": product.issuer_zh if lang() == "zh" and product.issuer_zh else product.issuer,
        "sale_to": product.sale_to,
        "promo": product.promo,
    }


def _product_source(product_id: str) -> str | None:
    meta = _fund_meta()["funds"].get(product_id)
    return meta["source"] if meta else None


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
        "notes": [explain_reason(code) for code in getattr(allocation, "reason_codes", ()) or ()],
        "stress_limit_before": getattr(allocation, "stress_limit_before", None),
        "stress_limit_after": getattr(allocation, "stress_limit_after", None),
        "holdings": [
            {
                "product_id": h.product_id,
                "name": _product_name(products[h.product_id]),
                "source": _product_source(h.product_id),
                "asset_class": h.asset_class,
                "risk_class": products[h.product_id].risk_class,
                "weight": h.weight,
                "amount": h.amount,
                "reasons": [explain_reason(code) for code in h.reason_codes],
                **_fixed_income_view(products[h.product_id]),
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
            "options": [{"key": option, "label": humanize(option, key)} for option in spec["options"]],
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
    file.session.update_client_facts({
        "amount": body.amount, "horizon_years": body.horizon_years,
        "max_loss": body.max_loss, "age": body.age, "borrowed_money": body.borrowed_money,
    })
    file.session.state.profile = profile
    file.session.state.profile_facts_version = file.session._profile_facts_version_current()
    file.session.state.profile_invalidated = False
    file.session.state.profile_version = file.session.current_profile_version()
    file.session.state.stage = AdvisoryStage.PROFILE_READY
    file.session.audit.append("profile_created", {"profile_version": file.session.state.profile_version, "class_code": profile.class_code})
    stamp = _record(file, "ui_profile_assessed", "profiling.profile_investor", {"profile": profile.as_dict()})
    return {"profile": _profile_view(profile), "client": _client(file), "provenance": stamp}


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
    amount = body.amount or _require_client(file, "amount")["amount"]
    try:
        allocation = build_allocation(
            amount, requested, load_catalog(), liquidity_days=profile.liquidity_days,
            horizon_years=_client(file).get("horizon_years"),
            max_tolerable_loss=_client(file).get("max_loss"),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    file.allocation_count += 1
    allocation_id = f"ui-{file.allocation_count}"
    file.session.state.allocations[allocation_id] = allocation
    file.session.register_allocation_recommendation(allocation_id, allocation)
    stamp = _record(file, "ui_allocation_built", "allocation.build_allocation", {"allocation_id": allocation_id, "allocation": allocation.as_dict()})
    file.allocation_provenance[allocation_id] = stamp
    return {"allocation_id": allocation_id, "allocation": _allocation_view(allocation), "provenance": stamp}


@app.get("/api/compare")
def compare(response: Response, asset_class: str | None = None, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    profile = _require_profile(file)
    catalog = load_catalog()
    client = _require_client(file, "amount", "horizon_years")
    rows = compare_products(
        catalog, client["amount"], client["horizon_years"], profile.investor_class,
        liquidity_days=profile.liquidity_days, asset_class=asset_class or None,
    )
    funds = [p for p in catalog if getattr(p, "kind", "fund") == "fund"]
    hidden = [{"name": _product_name(p), "risk_class": p.risk_class} for p in funds if p.risk_class > profile.investor_class]
    locked = [{"name": _product_name(p), "liquidity_days": p.liquidity_days} for p in funds if p.risk_class <= profile.investor_class and p.liquidity_days > profile.liquidity_days]
    stamp = _record(file, "ui_products_compared", "catalog.compare_products", {"asset_class": asset_class, "count": len(rows)})
    by_id = {p.id: p for p in catalog}
    view_rows = [{**row.as_dict(), **_fixed_income_view(by_id[row.product_id]), "name": _product_name(by_id[row.product_id]), "source": _product_source(row.product_id)} for row in rows]
    return {"rows": view_rows, "hidden": hidden, "locked": locked, "provenance": stamp}


@app.get("/api/stress")
def stress(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    file = _file(wa_sid, response)
    _require_profile(file)
    try:
        allocation = file.session.stored_allocation("latest")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    max_loss = _client(file).get("max_loss") or 0.2
    results = [stress_test(allocation, key, max_tolerable_loss=max_loss) for key in SCENARIOS]
    stamp = _record(file, "ui_stress_tested", "stress.stress_test", {"results": [r.as_dict() for r in results]})
    return {
        "max_loss": max_loss,
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
    file.session.state.goal = file.goal
    stamp = _record(file, "ui_goal_projected", "goals.project_goal", {"goal": body.model_dump(), "probability": result.probability, "required_monthly": result.required_monthly})
    return {"goal": body.model_dump(), "result": view, "initial": allocation.amount, "provenance": stamp}


@app.get("/api/rehearsal")
def rehearsal(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """The client's own portfolio replayed through 2007-2013, month by month."""

    file = _file(wa_sid, response)
    profile = _require_profile(file)
    try:
        allocation = file.session.stored_allocation("latest")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    scenario = load_scenario()
    path = portfolio_path(allocation, scenario)
    stamp = _record(file, "rehearsal_started", "rehearsal.portfolio_path", {"allocation_id": file.session.state.latest_allocation_id, "months": len(path)})
    answers = _answers_from_profile(profile)
    return {
        "amount": allocation.amount,
        "points": [{"month": p.month, "value": p.value, "drawdown": p.drawdown, "headline": p.headline} for p in path],
        "stated_reaction": answers.get("drawdown_reaction"),
        "stated_max_loss": _client(file).get("max_loss"),
        "investor_class": profile.investor_class,
        "sources": scenario["sources"],
        "method": scenario["method"],
        "provenance": stamp,
    }


class DecisionIn(BaseModel):
    action: Literal["sell", "hold", "buy_more"]
    month_index: int = Field(ge=0, le=200)


@app.post("/api/rehearsal/decision")
def rehearsal_decision(body: DecisionIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Score the client's behaviour; revealed tolerance can only lower the risk class."""

    file = _file(wa_sid, response)
    profile = _require_profile(file)
    try:
        allocation = file.session.stored_allocation("latest")
        outcome = evaluate(allocation, profile, body.action, body.month_index, stated_max_loss=_client(file).get("max_loss"))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    file.session.state.profile = apply_outcome(profile, outcome)
    view = outcome.as_dict()
    file.rehearsals.append(view)
    stamp = _record(file, "rehearsal_decision", "rehearsal.evaluate", {"outcome": view})
    return {"outcome": view, "profile": _profile_view(file.session.state.profile), "provenance": stamp}


@app.post("/api/market/event/{event}")
def market_event(event: str, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Proactive monitoring: apply a market event to the client's portfolio and prepare the advisor's message."""

    file = _file(wa_sid, response)
    _require_profile(file)
    if event not in EVENTS:
        raise HTTPException(404, "Unknown market event.")
    try:
        allocation = file.session.stored_allocation("latest")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    check = check_market(allocation, event, loss_limit=_client(file).get("max_loss"), rehearsal=file.rehearsals[-1] if file.rehearsals else None)
    view = check.as_dict()
    file.alerts.append(view)
    stamp = _record(file, "proactive_alert", "monitoring.check_market", {"check": view})
    return {"check": view, "provenance": stamp}


@app.get("/api/market/live")
def live_indices(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Return allowlisted index, gold, and FX observations with refresh provenance."""

    file = _file(wa_sid, response)
    quotes = [quote.as_dict() for quote in file.session.market.indices(file.session.audit)]
    stamp = _record(file, "market_quotes_viewed", "live_market.LiveMarket.indices", {"sources": [quote["source"] for quote in quotes], "as_of": [quote["as_of"] for quote in quotes]})
    return {"quotes": quotes, "provenance": stamp}


@app.get("/api/market/funds")
def live_funds(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Return NAV observations for CN holdings, or the full CN catalog without an allocation."""

    file = _file(wa_sid, response)
    allocation_id = file.session.state.latest_allocation_id
    ids = None
    if allocation_id:
        holding_ids = [holding.product_id for holding in file.session.state.allocations[allocation_id].holdings]
        if all(product_id.startswith("CN-") for product_id in holding_ids):
            ids = holding_ids
    quotes = [quote.as_dict() for quote in file.session.market.funds(ids, file.session.audit)]
    stamp = _record(file, "fund_nav_viewed", "live_market.LiveMarket.funds", {"sources": [quote["source"] for quote in quotes], "as_of": [quote["as_of"] for quote in quotes]})
    return {"quotes": quotes, "allocation_id": allocation_id, "provenance": stamp}


@app.post("/api/market/check-live")
def check_live(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Apply latest public fund NAV changes to the current portfolio and reuse monitoring policy."""

    file = _file(wa_sid, response)
    _require_profile(file)
    try:
        allocation = file.session.stored_allocation("latest")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        quotes = file.session.market.funds([holding.product_id for holding in allocation.holdings], file.session.audit)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    fund_ids = {holding.product_id for holding in allocation.holdings if not holding.product_id.startswith(("dep-", "lcd-", "sb-"))}
    if any(quote.stale or quote.change_pct is None for quote in quotes if quote.id in fund_ids):
        raise HTTPException(503, "Current NAV changes are unavailable for every holding; no live check was computed.")
    changes = {quote.id: quote.change_pct for quote in quotes if quote.change_pct is not None}
    check = check_live_market(allocation, changes, loss_limit=_client(file).get("max_loss"), rehearsal=file.rehearsals[-1] if file.rehearsals else None)
    view = check.as_dict()
    file.alerts.append(view)
    stamp = _record(file, "live_market_check", "monitoring.check_live_market", {"check": view, "sources": [quote.source for quote in quotes], "as_of": [quote.as_of for quote in quotes]})
    return {"check": view, "quotes": [quote.as_dict() for quote in quotes], "provenance": stamp}


class AlertDecisionIn(BaseModel):
    event: str
    choice: Literal["hold", "rebalance", "sell"]


@app.post("/api/market/decision")
def market_decision(body: AlertDecisionIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Record the client's decision after an alert. Rebalancing is an instruction for the simulated account."""

    file = _file(wa_sid, response)
    _require_profile(file)
    alert = next((a for a in reversed(file.alerts) if a["event"] == body.event), None)
    if alert is None:
        raise HTTPException(409, "No alert for this event in this session.")
    stamp = _record(file, "client_decision_after_alert", "ui.server.market_decision", {"event": body.event, "choice": body.choice, "recommendation": alert["recommendation"], "trades": alert["trades"] if body.choice == "rebalance" else []})
    return {"choice": body.choice, "followed_advice": body.choice == alert["recommendation"] or (alert["recommendation"] == "hold" and body.choice == "hold"), "provenance": stamp}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)


@app.post("/api/chat")
def chat(body: ChatIn, response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    ip = CLIENT_IP.get()
    limiter = _CHAT_LIMITERS.setdefault(ip, RateLimiter(max_calls=20, window_seconds=60))
    if not limiter.allow():
        raise HTTPException(429, "Too many chat requests from this address; try again later.", headers={"Retry-After": "60"})
    file = _file(wa_sid, response)
    try:
        reply = file.session.send(body.message)
    except Exception as exc:  # the UI shows the failure instead of hanging
        file.session.audit.append("chat_error", {"error": type(exc).__name__})
        raise HTTPException(502, "The advisor could not answer right now; please try again.") from exc
    # Shown to the client so they can see what actually reached the model.
    redacted, pii_types = redact_pii(body.message)
    return {"reply": reply, "mode": file.session.settings.llm_mode, "redacted": redacted, "pii_types": list(pii_types), "state": _ui_state(file)}


@app.get("/api/state")
def ui_state(response: Response, wa_sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Everything the UI needs to restore itself after a reload or a chat turn."""

    return _ui_state(_file(wa_sid, response))


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
        "name": _product_name(product),
        "asset_class": product.asset_class,
        "nav": product.nav,
        "price": order.get("price", product.nav),
        "units": order.get("units", order["amount"] / product.nav),
        "cooling_off": bool(cooling and date.fromisoformat(cooling) > date.today()),
    }


@app.get("/api/catalog-info")
def catalog_info() -> dict[str, Any]:
    meta = _fund_meta()
    real = bool(meta["funds"]) and os.getenv("WEALTH_ADVISOR_CATALOG", "").lower() == "cn"
    return {"real": real, "as_of": meta.get("as_of"), "source": meta.get("source"), "currency": meta.get("currency") if real else None, "count": len(load_catalog()), "anchor_network": anchor_network(), "anchor_note": ANCHOR_NOTE}


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
    try:
        recommendation = file.session.require_current_recommendation()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    file.session.tier = PermissionTier.EXECUTE
    file.signed = True
    # The signature name is personal data: only its hash enters the audit log.
    signer = hashlib.sha256(body.full_name.strip().lower().encode()).hexdigest()
    risk_disclosure_hash = canonical_hash({"text": "simulated-account risk disclosure", "recommendation_hash": recommendation.fingerprint})
    stamp = _record(file, "consent_signed", "ui.server.consent", {"signer_sha256": signer, "tier": "EXECUTE", "recommendation_hash": recommendation.fingerprint})
    try:
        file.session.record_client_consent("web_ui", risk_disclosure_hash)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    recommendation.status = ArtifactStatus.ACCEPTED.value
    file.session.state.stage = AdvisoryStage.CONSENT_REQUIRED
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
    """Write the session audit-chain head to Sepolia when a funded wallet is configured."""

    file = _file(wa_sid, response)
    path = Path(file.session.settings.audit_log)
    try:
        receipt = anchor_audit_log(path)
    except Exception as exc:  # network and RPC failures must not break the advice flow
        _record(file, "anchor_failed", "anchor.anchor_audit_log", {"error": type(exc).__name__, "message": str(exc)[:200]})
        raise HTTPException(503, "Sepolia anchoring is unavailable; the local session audit remains valid.") from exc
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

    LANG.set("en")  # the Advice Report is a formal English record, like the submission
    file = _file(wa_sid, response)
    profile = file.session.state.profile
    if profile is None:
        return HTMLResponse("<p style='font-family:sans-serif;padding:40px'>Complete the risk questionnaire first, then open the report again.</p>", status_code=409)
    try:
        allocation = file.session.stored_allocation("latest")
    except ValueError:
        allocation = None
    stress_results = [stress_test(allocation, key, max_tolerable_loss=_client(file).get("max_loss") or 0.2) for key in SCENARIOS] if allocation else []
    path = Path(file.session.settings.audit_log)
    valid, _ = verify_audit_log(path)
    count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) if path.exists() else 0
    html, digest = render_report(
        profile=profile, client=_client(file), allocation=allocation, stress=stress_results, goal=file.session.state.goal or file.goal,
        rehearsal=file.rehearsals[-1] if file.rehearsals else None,
        stated_reaction=_answers_from_profile(profile).get("drawdown_reaction"),
        products={p.id: p for p in load_catalog()}, audit_valid=valid, audit_records=count,
        signed=file.signed, model_mode=file.session.settings.llm_mode,
    )
    _record(file, "advice_report_issued", "ui.report.render_report", {"report_sha256": digest})
    return HTMLResponse(html)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main() -> None:
    import uvicorn

    # The web app advises on real Chinese public funds by default; tests keep the mock catalog.
    os.environ.setdefault("WEALTH_ADVISOR_CATALOG", "cn")
    os.environ.setdefault("CASH_RATE", "0.015")
    # Audit anchors go to the local WeBank FISCO BCOS consortium chain (scripts/fisco_chain.sh start).
    os.environ.setdefault("ANCHOR_NETWORK", "fisco")

    uvicorn.run("wealth_advisor.ui.server:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8600")), reload=False)
