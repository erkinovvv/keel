from datetime import date

import pytest

from wealth_advisor.config import Settings
from wealth_advisor.permissions import PermissionDenied, PermissionTier
from wealth_advisor.session import AdvisorSession


ANSWERS = {
    "horizon": "7_10y",
    "liquidity_need": "over_30d",
    "income_stability": "stable",
    "emergency_fund": "over_6_months",
    "invested_share": "under_25",
    "drawdown_reaction": "hold",
    "experience": "good",
    "goal": "growth",
}


def make_session(tmp_path, tier=PermissionTier.PROPOSE, **kwargs):
    settings = Settings(llm_mode="replay", audit_log=tmp_path / "audit.jsonl", **kwargs)
    session = AdvisorSession(settings, tier)
    session.dispatcher.dispatch("profile_investor", {"answers": ANSWERS, "age": 35})
    session.dispatcher.dispatch("build_allocation", {"amount": 100_000})
    return session


def test_permission_tiers_and_kill_switch(tmp_path):
    info = AdvisorSession(Settings(llm_mode="replay", audit_log=tmp_path / "info" / "audit.jsonl"), PermissionTier.INFO)
    with pytest.raises(PermissionDenied):
        info.dispatcher.dispatch("profile_investor", {"answers": ANSWERS})
    advise = make_session(tmp_path / "advise", PermissionTier.ADVISE)
    with pytest.raises(PermissionDenied):
        advise.create_draft_orders()
    locked = make_session(tmp_path / "locked", PermissionTier.EXECUTE, kill_switch=True)
    assert locked.tier == PermissionTier.ADVISE


def test_drafts_require_propose_and_confirmation_is_human_only(tmp_path):
    session = make_session(tmp_path)
    orders = session.create_draft_orders()
    assert orders
    order_id = next(item["order_id"] for item in orders if item["risk_class"] <= 3)
    with pytest.raises(PermissionDenied):
        session.confirm_order(order_id, "forged-token")

    execute = make_session(tmp_path / "execute", PermissionTier.EXECUTE)
    orders = execute.create_draft_orders()
    order = next(item for item in orders if item["risk_class"] <= 3)
    token = execute.issue_confirmation_token(order["order_id"])
    result = execute.confirm_order(order["order_id"], token)
    assert result["status"] == "EXECUTED"
    with pytest.raises(PermissionDenied):
        execute.confirm_order(order["order_id"], token)


def test_r4_r5_orders_have_cooling_off(tmp_path):
    session = make_session(tmp_path / "cooling", PermissionTier.EXECUTE)
    orders = session.create_draft_orders()
    high_risk = next(item for item in orders if item["risk_class"] >= 4)
    assert high_risk["cooling_off_until"] > date.today().isoformat()
    token = session.issue_confirmation_token(high_risk["order_id"])
    with pytest.raises(ValueError, match="cooling-off"):
        session.confirm_order(high_risk["order_id"], token)


def test_order_caps_are_enforced(tmp_path):
    session = make_session(tmp_path / "caps", PermissionTier.PROPOSE, max_order_amount=1_000)
    with pytest.raises(ValueError, match="per-order amount cap"):
        session.create_draft_orders()
