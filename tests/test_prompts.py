from wealth_advisor.prompts import SYSTEM_PROMPT


def test_prompt_covers_rehearsal_and_currency_rules() -> None:
    assert "Crash test (step 3)" in SYSTEM_PROMPT
    assert "currency symbols or currency names" in SYSTEM_PROMPT
    assert len(SYSTEM_PROMPT.split()) < 500
    assert "at most 70 words" in SYSTEM_PROMPT
    assert "at most one question per message" in SYSTEM_PROMPT
    assert "About you, Your plan, Crash test, Goal, or Invest" in SYSTEM_PROMPT
    assert "never as codes" in SYSTEM_PROMPT
    assert "never ask for a fact already shown there" in SYSTEM_PROMPT
    assert "no return can be guaranteed" in SYSTEM_PROMPT
    assert "35% per-product cap" in SYSTEM_PROMPT
    assert "Markdown" in SYSTEM_PROMPT
