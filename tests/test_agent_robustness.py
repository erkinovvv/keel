from wealth_advisor.agent import AdvisorAgent
from wealth_advisor.audit import AuditLogger
from wealth_advisor.config import Settings
from wealth_advisor.llm import LLMClient
from wealth_advisor.tools import ToolDispatcher


def test_tool_errors_are_returned_to_model_and_count_as_steps(tmp_path):
    fixture = tmp_path / "replay.json"
    fixture.write_text(
        '{"responses": [{"content": "", "tool_calls": [{"name": "unknown_tool", "arguments": {}}]}, '
        '{"content": "I need the profile details first.", "tool_calls": []}]}',
        encoding="utf-8",
    )
    audit = AuditLogger(tmp_path / "audit.jsonl")
    settings = Settings(llm_mode="replay", replay_file=fixture)
    response = AdvisorAgent(LLMClient(settings, audit), ToolDispatcher(audit), audit, 2).run("help")
    assert response == "I need the profile details first."
    assert any('"event":"tool_error"' in line for line in (tmp_path / "audit.jsonl").read_text().splitlines())


def test_malformed_replay_arguments_do_not_crash(tmp_path):
    fixture = tmp_path / "replay.json"
    fixture.write_text(
        '{"responses": [{"content": "", "tool_calls": [{"name": "profile_investor", "arguments": "not-json"}]}, '
        '{"content": "Please provide the enumerated answers.", "tool_calls": []}]}',
        encoding="utf-8",
    )
    settings = Settings(llm_mode="replay", replay_file=fixture)
    response = AdvisorAgent(LLMClient(settings), ToolDispatcher(), max_steps=2).run("profile me")
    assert "enumerated" in response
