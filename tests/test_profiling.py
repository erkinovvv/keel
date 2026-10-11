from datetime import date

import pytest

from wealth_advisor.profiling import profile_investor


BASE_ANSWERS = {
    "horizon": "7_10y",
    "income_stability": "stable",
    "emergency_fund": "over_6_months",
    "invested_share": "under_25",
    "drawdown_reaction": "hold",
    "experience": "good",
    "goal": "growth",
}


def test_profile_separates_capacity_tolerance_and_expires():
    profile = profile_investor(BASE_ANSWERS, age=40, as_of=date(2026, 1, 1))
    assert profile.capacity_class == 5
    assert profile.tolerance_class == 4
    assert profile.investor_class == 4
    assert profile.expires_on == date(2027, 1, 1)
    assert "HORIZON_7_10Y" in profile.reason_codes


def test_vulnerability_flags_cap_class():
    answers = dict(BASE_ANSWERS, horizon="under_1y", emergency_fund="none")
    profile = profile_investor(answers, age=75, borrowed_money=True)
    assert profile.investor_class == 1
    assert set(profile.vulnerability_flags) == {"AGE_70_PLUS", "NO_EMERGENCY_FUND", "BORROWED_MONEY", "SHORT_HORIZON"}
    assert "VULNERABILITY_CAP_APPLIED" in profile.reason_codes


def test_profile_rejects_unmapped_answers():
    with pytest.raises(ValueError, match="invalid option"):
        profile_investor(dict(BASE_ANSWERS, goal="free_text"))
