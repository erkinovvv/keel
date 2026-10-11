import math

import pytest

from wealth_advisor.allocation import MAX_PRODUCT_WEIGHT, build_allocation
from wealth_advisor.catalog import load_catalog


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
