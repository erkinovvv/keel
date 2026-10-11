import json

from wealth_advisor.agent import AdvisorAgent
from wealth_advisor.audit import AuditLogger
from wealth_advisor.allocation import build_allocation
from wealth_advisor.config import Settings
from wealth_advisor.llm import LLMClient
from wealth_advisor.tools import ToolDispatcher


def test_replay_is_offline_and_agent_is_bounded(tmp_path):
    audit = AuditLogger(tmp_path / "audit.jsonl")
    settings = Settings(llm_mode="replay", replay_file=tmp_path / "missing.json")
    client = LLMClient(settings, audit)
    response = client.chat([{"role": "user", "content": "hello"}])
    assert response.model == "replay"
    assert response.usage["total_tokens"] == 0
    assert "GROQ_API_KEY" in response.content
    assert "works offline" in response.content
    assert AdvisorAgent(client, ToolDispatcher(audit), audit, 1).run("hello")


def test_replay_unavailable_message_uses_client_language(tmp_path):
    settings = Settings(llm_mode="replay", replay_file=tmp_path / "missing.json")
    response = LLMClient(settings).chat([{"role": "user", "content": "请帮我建立投资组合"}])
    assert "GROQ_API_KEY" in response.content
    assert "离线运行" in response.content


def test_tool_dispatcher_validates_and_returns_json_ready_values(tmp_path):
    dispatcher = ToolDispatcher(AuditLogger(tmp_path / "audit.jsonl"))
    result = dispatcher.dispatch("profile_investor", {"answers": {
        "horizon": "7_10y", "income_stability": "stable", "emergency_fund": "over_6_months",
        "invested_share": "under_25", "drawdown_reaction": "hold", "experience": "good", "goal": "growth",
    }})
    assert result["class_code"].startswith("C")
    json.dumps(result)


def test_tool_schemas_use_explicit_units_and_errors_are_actionable(tmp_path):
    from wealth_advisor.tools import TOOL_SCHEMAS

    facts_schema = next(item for item in TOOL_SCHEMAS if item["function"]["name"] == "record_client_facts")["function"]["parameters"]
    assert "amount_cny" in facts_schema["properties"]
    assert "max_loss_fraction" in facts_schema["properties"]
    assert "amount" not in facts_schema["properties"]
    dispatcher = ToolDispatcher(AuditLogger(tmp_path / "audit.jsonl"))
    try:
        dispatcher.dispatch("record_client_facts", {"max_loss_fraction": 20})
    except ValueError as exc:
        assert "looks like a percent" in str(exc)
        assert "0.20" in str(exc)
    else:
        raise AssertionError("percent-like fraction should be rejected")


def test_model_tool_results_are_compact_and_display_ready(tmp_path):
    from wealth_advisor.tools import compact_tool_result

    compact = compact_tool_result(
        "build_allocation",
        {"allocation_id": "allocation-1", "investor_class": 3, "expected_return": 0.05, "volatility": 0.08, "holdings": [{"product_id": "BOND-1", "asset_class": "bonds", "weight": 0.4}]},
    )
    assert "holdings" not in compact
    assert "BOND-1" in compact["display"]


def test_tool_dispatcher_exposes_stress_test(tmp_path):
    from wealth_advisor.permissions import PermissionTier
    from wealth_advisor.session import AdvisorSession

    session = AdvisorSession(Settings(llm_mode="replay", audit_log=tmp_path / "audit.jsonl"), PermissionTier.ADVISE)
    session.dispatcher.dispatch("profile_investor", {"answers": {
        "horizon": "7_10y", "income_stability": "stable", "emergency_fund": "over_6_months",
        "invested_share": "under_25", "drawdown_reaction": "hold", "experience": "good", "goal": "growth",
    }})
    allocation = build_allocation(100_000, 3)
    session.state.allocations["allocation-1"] = allocation
    result = session.dispatcher.dispatch("stress_test", {"allocation_id": "allocation-1", "scenario": "2022_rate_shock"})
    assert result["scenario"] == "2022_rate_shock"
    assert result["loss_amount"] >= 0
