import dataclasses

import pytest

from wealth_advisor.allocation import build_allocation
from wealth_advisor.catalog import load_catalog
from wealth_advisor.profiling import QUESTIONNAIRE, profile_investor
from wealth_advisor.rehearsal import apply_outcome, evaluate, load_scenario, portfolio_path, revealed_class


@pytest.fixture
def setup():
    answers = {key: list(spec["options"])[-1] for key, spec in QUESTIONNAIRE.items()}  # most risk-tolerant answers
    profile = profile_investor(answers, age=30)
    allocation = build_allocation(100_000, profile.investor_class, load_catalog())
    return profile, allocation


def test_scenario_is_real_and_complete():
    scenario = load_scenario()
    assert scenario["base_month"] == "2007-09" and len(scenario["months"]) == 66
    assert all(set(row["returns"]) == {"equity", "bonds", "cash", "gold", "reits"} for row in scenario["months"])
    assert len(scenario["sources"]) == 4


def test_path_starts_at_amount_and_has_a_2008_drawdown(setup):
    profile, allocation = setup
    path = portfolio_path(allocation)
    assert path[0].value == pytest.approx(100_000) and path[0].month == "2007-09"
    trough = max(path, key=lambda p: p.drawdown)
    assert trough.month.startswith(("2008", "2009")) and trough.drawdown > 0.05


def test_revealed_class_thresholds():
    assert [revealed_class(d) for d in (0.02, 0.07, 0.12, 0.2, 0.4)] == [1, 2, 3, 4, 5]


def test_selling_at_the_bottom_lowers_the_class_and_costs_money(setup):
    profile, allocation = setup
    path = portfolio_path(allocation)
    trough_index = max(range(len(path)), key=lambda i: path[i].drawdown)
    outcome = evaluate(allocation, profile, "sell", trough_index)
    assert outcome.final_value_of_choice < outcome.final_value_if_held
    assert outcome.new_class <= profile.investor_class
    updated = apply_outcome(profile, outcome)
    assert updated.investor_class == outcome.new_class
    assert updated.reason_codes[-1] == outcome.reason_code


def test_holding_never_raises_the_class(setup):
    profile, allocation = setup
    low = dataclasses.replace(profile, investor_class=2)
    for action in ("hold", "buy_more"):
        outcome = evaluate(allocation, low, action, 10)
        assert outcome.new_class == 2 and outcome.revealed_class is None


def test_early_panic_reveals_low_tolerance(setup):
    profile, allocation = setup
    path = portfolio_path(allocation)
    first_dip = next(i for i, p in enumerate(path) if 0.0 < p.drawdown < 0.05)
    outcome = evaluate(allocation, profile, "sell", first_dip)
    assert outcome.revealed_class == 1 and apply_outcome(profile, outcome).investor_class == 1


def test_month_index_is_validated(setup):
    profile, allocation = setup
    with pytest.raises(ValueError):
        evaluate(allocation, profile, "sell", 999)
