import math
import json
from pathlib import Path

import pytest

from wealth_advisor.allocation import MAX_PRODUCT_WEIGHT, build_allocation
from wealth_advisor.catalog import load_catalog
from wealth_advisor.stress import SCENARIOS, stress_test


@pytest.mark.parametrize("investor_class", range(1, 6))
def test_allocation_constraints_hold(investor_class):
    allocation = build_allocation(100_000, investor_class, load_catalog())
    assert math.isclose(sum(item.weight for item in allocation.holdings), 1.0)
    assert all(0 <= item.weight <= MAX_PRODUCT_WEIGHT + 1e-9 for item in allocation.holdings)
    assert all(item.amount >= load_catalog()[next(index for index, product in enumerate(load_catalog()) if product.id == item.product_id)].min_investment for item in allocation.holdings)
    assert allocation.expected_return >= 0
    assert allocation.volatility >= 0
    assert allocation.var_95_1y >= 0
    assert allocation.var_95_1y_parametric == allocation.var_95_1y
    assert allocation.volatility_band[0] <= allocation.volatility_band[1]


def test_allocation_respects_suitability_and_exclusions():
    allocation = build_allocation(100_000, 2, exclusions=["EQ-DIV", "equity"])
    assert all(item.asset_class != "equity" for item in allocation.holdings)
    assert all(int(item.reason_codes[0][-1]) <= 2 for item in allocation.holdings)


def test_allocation_final_split_respects_minimums():
    catalog = load_catalog()
    allocation = build_allocation(10_000, 5, catalog)
    by_id = {product.id: product for product in catalog}
    assert all(item.amount + 1e-9 >= by_id[item.product_id].min_investment for item in allocation.holdings)


def test_all_journey_personas_build_allocations():
    personas = json.loads((Path(__file__).parents[1] / "evals" / "journeys" / "personas.json").read_text())
    for persona in personas:
        profile_class = persona["expected_class"]
        liquidity = {"within_1d": 1, "within_7d": 7, "within_30d": 30, "over_30d": 365}[persona["answers"]["liquidity_need"]]
        allocation = build_allocation(persona["amount"], profile_class, liquidity_days=liquidity)
        assert math.isclose(sum(item.weight for item in allocation.holdings), 1.0)
        if liquidity <= 30:
            sleeve_days = 1 if liquidity == 1 else 7 if liquidity == 7 else 30
            sleeve_target = 0.30 if liquidity == 1 else 0.20 if liquidity == 7 else 0.10
            assert sum(item.weight for item in allocation.holdings if load_catalog()[next(i for i, product in enumerate(load_catalog()) if product.id == item.product_id)].liquidity_days <= sleeve_days) >= sleeve_target - 1e-9


def test_stress_limit_reweights_before_recommending():
    unconstrained = build_allocation(100_000, 4)
    constrained = build_allocation(100_000, 4, max_tolerable_loss=0.20)
    assert "STRESS_LIMIT_APPLIED" in constrained.reason_codes
    assert constrained.stress_limit_before == max(stress_test(unconstrained, scenario).loss_percent for scenario in SCENARIOS)
    assert constrained.stress_limit_after == pytest.approx(max(stress_test(constrained, scenario).loss_percent for scenario in SCENARIOS))
    assert constrained.stress_limit_after <= 0.20 + 1e-9
    assert constrained.strategic_weights["equity"] + constrained.strategic_weights["reits"] < unconstrained.strategic_weights["equity"] + unconstrained.strategic_weights["reits"]


def test_stress_limit_may_step_down_class():
    allocation = build_allocation(100_000, 4, max_tolerable_loss=0.10)
    assert allocation.investor_class < 4
    assert "STRESS_LIMIT_APPLIED" in allocation.reason_codes
    assert max(stress_test(allocation, scenario).loss_percent for scenario in SCENARIOS) <= 0.10 + 1e-9
