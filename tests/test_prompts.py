from wealth_advisor.prompts import SYSTEM_PROMPT


def test_prompt_covers_rehearsal_and_currency_rules() -> None:
    assert "Rehearse step 3" in SYSTEM_PROMPT
    assert "currency symbols or currency names" in SYSTEM_PROMPT
    assert len(SYSTEM_PROMPT.split()) < 500
    assert "at most 70 words" in SYSTEM_PROMPT
    assert "at most one question per message" in SYSTEM_PROMPT
    assert "Risk profile, Portfolio, Rehearse, Goal, or Invest" in SYSTEM_PROMPT
