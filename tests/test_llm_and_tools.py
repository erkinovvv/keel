import json

from wealth_advisor.agent import AdvisorAgent, shape_reply
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


def test_replay_reply_is_shaped_to_three_paragraphs_and_100_words(tmp_path):
    fixture = tmp_path / "replay.json"
    fixture.write_text(
        '{"responses": [{"content": "' + " ".join(["word"] * 98) + '. Second sentence is omitted.", "tool_calls": []}]}',
        encoding="utf-8",
    )
    settings = Settings(llm_mode="replay", replay_file=fixture)
    result = AdvisorAgent(LLMClient(settings), ToolDispatcher(), max_steps=1).run("hello")
    assert len(result.split()) <= 100
    assert len([paragraph for paragraph in result.split("\n\n") if paragraph]) <= 3
    assert result.endswith(".")
    assert "Second sentence" not in result


def test_reply_shaping_keeps_a_long_first_sentence_without_ellipsis():
    result = shape_reply("".join(["long "] * 120) + ". Next sentence is omitted.")
    assert result.endswith(".")
    assert "Next sentence" not in result
    assert "…" not in result


def test_reply_shaping_counts_chinese_characters_and_keeps_sentences():
    result = shape_reply("第一句已经完整。" + "这是一段很长的中文内容。" * 20 + "第二句不应出现。")
    assert len(result) <= 180
    assert result.endswith("。")
    assert "第二句不应出现" not in result


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
    from wealth_advisor.catalog import load_catalog

    catalog = load_catalog()
    product = catalog[0]
    compact = compact_tool_result(
        "build_allocation",
        {"allocation_id": "allocation-1", "investor_class": 3, "expected_return": 0.05, "volatility": 0.08, "holdings": [{"product_id": product.id, "asset_class": product.asset_class, "weight": 0.4}]},
        catalog,
    )
    assert "holdings" not in compact
    assert product.name in compact["display"]
    assert "allocation-1" not in compact["display"]
    assert product.id not in compact["display"]


def test_allocation_capped_by_client_loss_limit_says_so():
    from wealth_advisor.catalog import load_catalog
    from wealth_advisor.tools import compact_tool_result

    catalog = load_catalog()
    allocation = build_allocation(50_000, 3, catalog, max_tolerable_loss=0.05)
    assert allocation.stress_limit_after is not None
    display = compact_tool_result("build_allocation", allocation.as_dict(), catalog)["display"]
    assert "client's own maximum-loss answer, not by the risk class" in display
    plain = compact_tool_result("build_allocation", build_allocation(50_000, 3, catalog).as_dict(), catalog)["display"]
    assert "Scaled back" not in plain


def test_stage_tool_lists_preserve_canonical_order(tmp_path):
    from wealth_advisor.permissions import PermissionTier
    from wealth_advisor.session import AdvisorSession
    from wealth_advisor.tools import TOOL_SCHEMAS

    canonical = [item["function"]["name"] for item in TOOL_SCHEMAS]
    session = AdvisorSession(Settings(llm_mode="replay", audit_log=tmp_path / "audit.jsonl"), PermissionTier.ADVISE)
    first_stage = [item["function"]["name"] for item in session._tools_for_state()]
    assert first_stage == [name for name in canonical if name in {"record_client_facts", "profile_investor", "market_quotes"}]


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
