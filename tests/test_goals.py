import math

import pytest

from wealth_advisor.goals import GoalInput, project_goal, required_monthly


def test_zero_volatility_matches_compound_growth():
    goal = GoalInput(target=1, years=10, initial=100_000, expected_return=0.05, volatility=0.0)
    result = project_goal(goal, paths=200)
    assert result.terminal_p50 == pytest.approx(100_000 * 1.05**10, rel=1e-9)


def test_projection_is_reproducible():
    goal = GoalInput(target=300_000, years=8, initial=100_000, monthly=1_000, expected_return=0.06, volatility=0.12)
    assert project_goal(goal, paths=1_000).as_dict() == project_goal(goal, paths=1_000).as_dict()


def test_more_saving_never_lowers_probability():
    base = dict(target=300_000, years=8, initial=100_000, expected_return=0.06, volatility=0.12)
    probabilities = [project_goal(GoalInput(monthly=m, **base), paths=1_000).probability for m in (0, 500, 1_000, 2_000)]
    assert probabilities == sorted(probabilities)


def test_required_monthly_reaches_confidence():
    goal = GoalInput(target=300_000, years=8, initial=100_000, expected_return=0.06, volatility=0.12)
    needed = required_monthly(goal, 300_000, paths=1_000)
    assert needed and needed > 0
    reached = project_goal(GoalInput(**{**goal.__dict__, "monthly": needed}), paths=1_000)
    assert reached.probability >= 0.80


def test_inflation_raises_the_nominal_target():
    goal = GoalInput(target=100_000, years=10, initial=50_000, inflation=0.02)
    assert project_goal(goal, paths=200).target_nominal == pytest.approx(100_000 * 1.02**10)


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError):
        project_goal(GoalInput(target=-1, years=5, initial=0))
    with pytest.raises(ValueError):
        project_goal(GoalInput(target=1, years=0, initial=0))
