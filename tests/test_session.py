import json
from datetime import date, timedelta
from dataclasses import replace

import pytest

from wealth_advisor.config import Settings
from wealth_advisor.agent import AgentTurn
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
    session.dispatcher.dispatch("record_client_facts", {"age": 35, "borrowed_money": False, "max_loss": 20})
    assert session.state.client.as_dict() == {
        "amount": 100_000.0,
        "horizon_years": 8,
        "max_loss": 0.2,
        "age": 35,
        "borrowed_money": False,
    }
    with pytest.raises(ValueError):
        session.dispatcher.dispatch("record_client_facts", {"max_loss": 101})


def test_percentage_tool_arguments_are_normalised(tmp_path):
    session = make_session(tmp_path)
    result = session.dispatcher.dispatch("record_client_facts", {"max_loss": 20})
    assert result["client"]["max_loss"] == 0.2
    session.dispatcher.dispatch("profile_investor", {"answers": ANSWERS})
    session.dispatcher.dispatch("record_client_facts", {"amount": 100_000})
    allocation = session.dispatcher.dispatch("build_allocation", {"max_tolerable_loss": 20})
    assert allocation["stress_limit_after"] is None or allocation["stress_limit_after"] <= 0.2 + 1e-9


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


def test_allocation_tool_uses_revealed_class_and_client_loss_limit(tmp_path):
    session = make_session(tmp_path)
    session.dispatcher.dispatch("profile_investor", {"answers": ANSWERS})
    session.dispatcher.dispatch("record_client_facts", {"amount": 100_000, "max_loss": 0.02})
    session.state.profile = replace(session.state.profile, investor_class=3, reason_codes=(*session.state.profile.reason_codes, "REVEALED_TOLERANCE_C3"))
    allocation = session.dispatcher.dispatch("build_allocation", {})
    assert allocation["investor_class"] <= 3
    assert allocation["stress_limit_after"] <= 0.02 + 1e-9
    assert "STRESS_LIMIT_APPLIED" in allocation["reason_codes"]


def test_guard_fallback_does_not_claim_empty_session_is_complete(tmp_path):
    session = make_session(tmp_path)
    turn_messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "The result is 123."},
    ]
    session.agent.run_turn = lambda messages, tools=None: AgentTurn("The result is 123.", turn_messages.copy(), [], {})
    reply = session.send("hello")
    assert reply == "What amount are you considering investing?"
    assert "complete" not in reply.lower()


def test_guard_regeneration_receives_exact_ungrounded_figures(tmp_path):
    session = make_session(tmp_path)
    calls: list[list[dict[str, object]]] = []

    def run_turn(messages, tools=None):
        calls.append(messages)
        content = "The result is 23%." if len(calls) == 1 else "Please share the next fact when you are ready."
        return AgentTurn(content, [*messages, {"role": "assistant", "content": content}], [], {})

    session.agent.run_turn = run_turn
    assert session.send("hello") == "Please share the next fact when you are ready."
    assert "23%" in calls[1][-1]["content"]
    assert "ungrounded figures" in calls[1][-1]["content"]


def test_session_passes_exact_settings_to_llm_and_prompt_guard(tmp_path):
    settings = Settings(
        llm_mode="live",
        groq_api_key="session-only-key",
        primary_model="session-model",
        audit_log=tmp_path / "audit.jsonl",
    )
    session = AdvisorSession(settings)
    assert session.agent.llm.settings is settings
    assert session.agent.llm.settings.groq_api_key == "session-only-key"
    assert session.agent.llm.settings.primary_model == "session-model"
    assert session.prompt_guard.settings is settings


def test_complete_first_message_gets_no_greeting_directive(tmp_path):
    session = make_session(tmp_path)
    message = (
        "I am 42 with 100000 for 8 years, can lose 20%, need it within a week, "
        "stable income, six months emergency cash, half my savings invested, "
        "would hold after a fall, know funds, and want growth. Build a portfolio."
    )
    system = session._messages_for_turn(message)[0]["content"]
    assert "do not greet or ask for the goal" in system


def test_complete_state_fallback_omits_empty_missing_clause():
    reply = AdvisorSession._state_fallback_message(
        {"profile": {}, "allocation": {}, "stress_results": {"stress-1": {}}},
        "the client's language",
    )
    assert reply == "Your investor profile, allocation, and stress test are recorded. Next, review the result or try the Crash Rehearsal before any orders."
    assert "Stored in this session" not in reply
