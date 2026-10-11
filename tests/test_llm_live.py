import json
from types import SimpleNamespace

from wealth_advisor.agent import AdvisorAgent
from wealth_advisor.audit import AuditLogger
from wealth_advisor.config import Settings
from wealth_advisor.llm import LLMClient
from wealth_advisor.tools import ToolDispatcher


def response(content="", tool_calls=None, total_tokens=7):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=total_tokens)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def tool_call(name, arguments, call_id="call-1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes):
        self.chat = SimpleNamespace(completions=FakeCompletions(outcomes))


class RateLimitError(Exception):
    status_code = 429

    def __init__(self, retry_after="1"):
        super().__init__("rate limited")
        self.response = SimpleNamespace(headers={"retry-after": retry_after})


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


def live_settings(tmp_path):
    return Settings(llm_mode="live", groq_api_key="test-key", audit_log=tmp_path / "audit.jsonl", fallback_models=("fallback-model",))


def test_live_tool_call_round_trip_and_turn_metrics(tmp_path):
    fake = FakeClient([
        response(tool_calls=[tool_call("profile_investor", json.dumps({"answers": ANSWERS}))]),
        response("Profile recorded.", total_tokens=9),
    ])
    audit = AuditLogger(tmp_path / "audit.jsonl")
    client = LLMClient(live_settings(tmp_path), audit, fake)
    dispatcher = ToolDispatcher(audit)
    agent = AdvisorAgent(client, dispatcher, audit, max_steps=2)
    turn = agent.run_turn([agent.system_message(), {"role": "user", "content": "profile me"}])
    assert turn.content == "Profile recorded."
    assert turn.usage["total_tokens"] == 16
    records = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert records[0]["event"] == "llm_call"
    assert records[0]["details"]["usage"]["total_tokens"] == 7
    assert records[0]["details"]["latency_ms"] >= 0
    assert fake.chat.completions.calls[0]["extra_body"] == {"reasoning_format": "hidden"}
    assert len(fake.chat.completions.calls) == 2


def test_live_429_falls_through_to_fallback_model(tmp_path):
    fake = FakeClient([RateLimitError("busy"), response("fallback", total_tokens=4)])
    audit = AuditLogger(tmp_path / "audit.jsonl")
    client = LLMClient(live_settings(tmp_path), audit, fake)
    result = client.chat([{"role": "user", "content": "hello"}])
    assert result.model == "fallback-model"
    assert result.content == "fallback"
    assert len(fake.chat.completions.calls) == 2


def test_live_retries_an_all_429_chain_twice(tmp_path, monkeypatch):
    fake = FakeClient([
        RateLimitError("31"), RateLimitError("2"),
        RateLimitError("4"), RateLimitError("3"),
        response("recovered", total_tokens=4),
    ])
    audit = AuditLogger(tmp_path / "audit.jsonl")
    waits = []
    monkeypatch.setattr("wealth_advisor.llm.time.sleep", waits.append)
    client = LLMClient(live_settings(tmp_path), audit, fake)
    result = client.chat([{"role": "user", "content": "hello"}])
    assert result.content == "recovered"
    assert waits == [2.0, 3.0]
    records = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [record["event"] for record in records].count("llm_retry_wait") == 2


def test_session_exposes_tools_by_stage(tmp_path):
    from wealth_advisor.permissions import PermissionTier
    from wealth_advisor.session import AdvisorSession

    session = AdvisorSession(Settings(llm_mode="replay", audit_log=tmp_path / "audit.jsonl"), PermissionTier.ADVISE)
    assert {item["function"]["name"] for item in session._tools_for_state()} == {"record_client_facts", "profile_investor"}
    session.dispatcher.dispatch("record_client_facts", {"amount": 100_000, "horizon_years": 5})
    session.dispatcher.dispatch("profile_investor", {"answers": {
        "horizon": "3_7y", "liquidity_need": "within_7d", "income_stability": "stable",
        "emergency_fund": "over_6_months", "invested_share": "under_25", "drawdown_reaction": "hold",
        "experience": "good", "goal": "growth",
    }})
    assert {item["function"]["name"] for item in session._tools_for_state()} == {"build_allocation", "compare_products"}


def test_live_malformed_json_reaches_tool_error_recovery(tmp_path):
    fake = FakeClient([
        response(tool_calls=[tool_call("profile_investor", "{not-json")]),
        response("Please provide valid questionnaire keys.")
    ])
    settings = live_settings(tmp_path)
    audit = AuditLogger(tmp_path / "audit.jsonl")
    client = LLMClient(settings, audit, fake)
    agent = AdvisorAgent(client, ToolDispatcher(audit), audit, max_steps=2)
    result = agent.run("profile me")
    assert result == "Please provide valid questionnaire keys."
    assert any(json.loads(line)["event"] == "tool_error" for line in (tmp_path / "audit.jsonl").read_text().splitlines())


def test_profile_schema_inlines_all_enumerated_questionnaire_fields():
    from wealth_advisor.tools import TOOL_SCHEMAS

    schema = next(item for item in TOOL_SCHEMAS if item["function"]["name"] == "profile_investor")["function"]["parameters"]
    answers = schema["properties"]["answers"]
    assert "$ref" not in answers
    assert set(answers["properties"]) == {
        "horizon", "liquidity_need", "income_stability", "emergency_fund",
        "invested_share", "drawdown_reaction", "experience", "goal",
    }
    assert "buy_more" in answers["properties"]["drawdown_reaction"]["enum"]
    assert "two thirds" in answers["properties"]["invested_share"]["description"]
    assert "sell some" in answers["properties"]["drawdown_reaction"]["description"]
    assert "under_1y is less than one year" in answers["properties"]["horizon"]["description"]
