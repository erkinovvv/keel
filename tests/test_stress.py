from wealth_advisor.allocation import build_allocation
from wealth_advisor.stress import stress_test


def test_stress_returns_currency_loss_and_mismatch():
    allocation = build_allocation(50_000, 3)
    result = stress_test(allocation, "2008_gfc", max_tolerable_loss=0.01)
    assert result.loss_amount == allocation.amount * result.loss_percent
    assert result.mismatch


def test_custom_stress_is_supported():
    allocation = build_allocation(50_000, 2)
    result = stress_test(allocation, "custom", custom_shocks={"cash": 0, "bonds": 0, "equity": -0.1, "gold": 0, "reits": -0.1})
    assert result.loss_percent >= 0

