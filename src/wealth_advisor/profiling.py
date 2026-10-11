"""Deterministic investor profiling under a C1-C5 suitability model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any


QUESTIONNAIRE: dict[str, dict[str, Any]] = {
    "horizon": {"domain": "capacity", "options": {"under_1y": 0, "1_3y": 1, "3_7y": 2, "7_10y": 3, "over_10y": 4}},
    "income_stability": {"domain": "capacity", "options": {"unstable": 0, "mixed": 1, "stable": 2}},
    "emergency_fund": {"domain": "capacity", "options": {"none": 0, "3_6_months": 2, "over_6_months": 4}},
    "invested_share": {"domain": "capacity", "options": {"over_75": 0, "50_75": 1, "25_50": 2, "under_25": 4}},
    "drawdown_reaction": {"domain": "tolerance", "options": {"sell_all": 0, "reduce": 1, "hold": 3, "buy_more": 4}},
    "experience": {"domain": "tolerance", "options": {"none": 0, "basic": 1, "good": 3, "advanced": 4}},
    "goal": {"domain": "tolerance", "options": {"preserve": 0, "income": 1, "growth": 3, "aggressive_growth": 4}},
}

_THRESHOLDS = ((2, 1), (5, 2), (8, 3), (11, 4))


@dataclass(frozen=True)
class InvestorProfile:
    investor_class: int
    capacity_score: int
    tolerance_score: int
    capacity_class: int
    tolerance_class: int
    reason_codes: tuple[str, ...]
    vulnerability_flags: tuple[str, ...]
    expires_on: date

    @property
    def class_code(self) -> str:
        return f"C{self.investor_class}"

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["expires_on"] = self.expires_on.isoformat()
        result["class_code"] = self.class_code
        return result


def _class_for_score(score: int) -> int:
    for ceiling, investor_class in _THRESHOLDS:
        if score <= ceiling:
            return investor_class
    return 5


def profile_investor(
    answers: dict[str, str],
    *,
    age: int | None = None,
    borrowed_money: bool = False,
    as_of: date | None = None,
) -> InvestorProfile:
    """Score objective capacity and behavioral tolerance separately, then take their minimum."""

    unknown = set(answers) - set(QUESTIONNAIRE)
    missing = set(QUESTIONNAIRE) - set(answers)
    if unknown or missing:
        raise ValueError(f"answers must contain exactly the questionnaire keys; missing={sorted(missing)}, unknown={sorted(unknown)}")
    reason_codes: list[str] = []
    capacity_score = 0
    tolerance_score = 0
    for question, answer in answers.items():
        options = QUESTIONNAIRE[question]["options"]
        if answer not in options:
            raise ValueError(f"invalid option {answer!r} for {question}")
        points = options[answer]
        domain = QUESTIONNAIRE[question]["domain"]
        if domain == "capacity":
            capacity_score += points
        else:
            tolerance_score += points
        reason_codes.append(f"{question.upper()}_{answer.upper()}")

    flags: list[str] = []
    if age is not None and age >= 70:
        flags.append("AGE_70_PLUS")
    if answers["emergency_fund"] == "none":
        flags.append("NO_EMERGENCY_FUND")
    if borrowed_money:
        flags.append("BORROWED_MONEY")
    if answers["horizon"] == "under_1y":
        flags.append("SHORT_HORIZON")

    capacity_class = _class_for_score(capacity_score)
    tolerance_class = _class_for_score(tolerance_score)
    investor_class = min(capacity_class, tolerance_class)
    if flags:
        investor_class = min(investor_class, 1 if "SHORT_HORIZON" in flags else 2)
        reason_codes.append("VULNERABILITY_CAP_APPLIED")
    effective_date = as_of or date.today()
    return InvestorProfile(
        investor_class=investor_class,
        capacity_score=capacity_score,
        tolerance_score=tolerance_score,
        capacity_class=capacity_class,
        tolerance_class=tolerance_class,
        reason_codes=tuple(reason_codes),
        vulnerability_flags=tuple(flags),
        expires_on=effective_date + timedelta(days=365),
    )

