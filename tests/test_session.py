import json
from datetime import date, timedelta
from dataclasses import replace

import pytest

from wealth_advisor.config import Settings
from wealth_advisor.permissions import PermissionTier
from wealth_advisor.session import AdvisorSession


ANSWERS = {
    "horizon": "7_10y",
    "income_stability": "stable",
    "emergency_fund": "over_6_months",
    "invested_share": "under_25",
    "drawdown_reaction": "hold",
    "experience": "good",
    "goal": "growth",
}


def make_session(tmp_path):
    return AdvisorSession(Settings(llm_mode="replay", audit_log=tmp_path / "audit.jsonl"), PermissionTier.ADVISE)


def test_session_tools_use_stored_profile_and_allocation_ids(tmp_path):
    session = make_session(tmp_path)
    session.dispatcher.dispatch("profile_investor", {"answers": ANSWERS})
    assert session.state.profile.class_code == "C4"
    result = session.dispatcher.dispatch("compare_products", {"amount": 100_000, "horizon_years": 10})
    assert all(item["risk_class"] <= 4 for item in result["comparisons"])
    allocation = session.dispatcher.dispatch("build_allocation", {"amount": 100_000})
    assert allocation["allocation_id"] == "allocation-1"
    stress = session.dispatcher.dispatch("stress_test", {"allocation_id": "latest"})
    assert stress["allocation_id"] == "latest"
    assert "allocation" not in stress


def test_session_rejects_missing_or_expired_profile(tmp_path):
    session = make_session(tmp_path)
    with pytest.raises(ValueError, match="profile first"):
        session.dispatcher.dispatch("compare_products", {"amount": 1_000, "horizon_years": 1})
    session.dispatcher.dispatch("profile_investor", {"answers": ANSWERS})
    session.state.profile = replace(session.state.profile, expires_on=date.today() - timedelta(days=1))
    with pytest.raises(ValueError, match="profile expired"):
        session.dispatcher.dispatch("compare_products", {"amount": 1_000, "horizon_years": 1})


def test_session_history_keeps_complete_tool_turns(tmp_path):
    session = make_session(tmp_path)
    session.send("hello")
    assert session.messages[0]["role"] == "system"
    assert session.messages[-1]["role"] == "assistant"
    json.dumps(session.messages)


def test_session_state_summary_keeps_financial_context(tmp_path):
    session = make_session(tmp_path)
    session.dispatcher.dispatch("profile_investor", {"answers": ANSWERS})
    session.dispatcher.dispatch("compare_products", {"amount": 12_000, "horizon_years": 8})
    summary = session.state.summary()
    assert summary["profile_class"] == "C4"
    assert summary["amount"] == 12_000
    assert summary["horizon_years"] == 8


def test_record_client_facts_is_validated_and_merged(tmp_path):
    session = make_session(tmp_path)
    session.dispatcher.dispatch("record_client_facts", {"amount": 100_000, "horizon_years": 8})
    session.dispatcher.dispatch("record_client_facts", {"age": 35, "borrowed_money": False, "max_loss": 0.2})
    assert session.state.client.as_dict() == {
        "amount": 100_000.0,
        "horizon_years": 8,
        "max_loss": 0.2,
        "age": 35,
        "borrowed_money": False,
    }
    with pytest.raises(ValueError):
        session.dispatcher.dispatch("record_client_facts", {"max_loss": 1.5})


def test_snapshot_is_json_serializable_and_contains_latest_artifacts(tmp_path):
    session = AdvisorSession(Settings(llm_mode="replay", audit_log=tmp_path / "audit.jsonl"), PermissionTier.PROPOSE)
    session.dispatcher.dispatch("record_client_facts", {"amount": 100_000, "horizon_years": 8, "max_loss": 0.2, "age": 35, "borrowed_money": False})
    session.dispatcher.dispatch("profile_investor", {"answers": ANSWERS})
    session.dispatcher.dispatch("build_allocation", {})
    session.dispatcher.dispatch("stress_test", {})
    snapshot = session.snapshot()
    json.dumps(snapshot)
    assert snapshot["client"]["amount"] == 100_000.0
    assert snapshot["latest_allocation_id"] == "allocation-1"
    assert snapshot["allocation"]["amount"] == 100_000
    assert snapshot["stress_results"]["stress-1"]["scenario"] == "2008_gfc"
    assert snapshot["tier"] == "PROPOSE"


def test_session_liquidity_need_excludes_long_lockup(tmp_path):
    session = make_session(tmp_path)
    session.dispatcher.dispatch("profile_investor", {"answers": dict(ANSWERS, liquidity_need="within_7d")})
    result = session.dispatcher.dispatch("compare_products", {"amount": 100_000, "horizon_years": 5})
    assert "CASH-DEP" not in {item["product_id"] for item in result["comparisons"]}
