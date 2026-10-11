from wealth_advisor.prompts import SYSTEM_PROMPT


def test_prompt_covers_rehearsal_and_currency_rules() -> None:
    assert "Crash Rehearsal" in SYSTEM_PROMPT
    assert "currency symbols or currency names" in SYSTEM_PROMPT
    assert len(SYSTEM_PROMPT.split()) < 500
