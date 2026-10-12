from datetime import date
from pathlib import Path

import pytest

from wealth_advisor.account import SimulatedAccount
from wealth_advisor.allocation import Allocation, Holding, build_allocation
from wealth_advisor.catalog import compare_products, early_withdrawal_value, fixed_income_available, load_catalog, load_fixed_income_cn
from wealth_advisor.profiling import profile_investor
from wealth_advisor.rehearsal import portfolio_path
from wealth_advisor.stress import stress_test


ANSWERS = {
    "horizon": "over_10y", "liquidity_need": "over_30d", "income_stability": "stable",
    "emergency_fund": "over_6_months", "invested_share": "under_25", "drawdown_reaction": "hold",
    "experience": "good", "goal": "preserve",
}


def test_fixed_income_rows_load_as_r1_products_and_early_value_is_deterministic():
    products = load_fixed_income_cn()
    deposit = next(product for product in products if product.kind == "deposit" and product.term_months == 12)
    bond = next(product for product in products if product.kind == "savings_bond")
    assert deposit.risk_class == bond.risk_class == 1
    assert deposit.volatility == bond.volatility == deposit.fee == bond.fee == 0
    assert deposit.expected_return == pytest.approx(deposit.expected_return)
    assert early_withdrawal_value(deposit, 100_000, 6) == pytest.approx(100_000 * (1 + 0.0005 * 0.5))
    assert early_withdrawal_value(bond, 100_000, 3) == pytest.approx(99_900)
    assert early_withdrawal_value(bond, 100_000, bond.term_months) > 100_000


def test_fixed_income_availability_and_comparison_expose_cost_and_insurance():
    catalog = load_fixed_income_cn()
    bond = next(product for product in catalog if product.kind == "savings_bond")
    assert fixed_income_available(bond, date(2026, 10, 12))
    assert not fixed_income_available(bond, date(2026, 11, 1))
    rows = compare_products(catalog, 100_000, 10, 1, kind="deposit", today=date(2026, 10, 12))
    assert rows and all(row.kind == "deposit" for row in rows)
    assert all(row.rate is not None and row.early_withdrawal_cost_6m >= 0 and row.insured for row in rows)


def test_allocation_uses_fixed_income_only_when_horizon_covers_term_and_splits_insurance():
    catalog = load_fixed_income_cn()
    long = build_allocation(2_000_000, 1, catalog, horizon_years=10, liquidity_days=365)
    fixed = [holding for holding in long.holdings if next(product for product in catalog if product.id == holding.product_id).kind in {"deposit", "large_cd", "savings_bond"}]
    assert fixed and "DEPOSIT_INSURANCE_SPLIT" in long.reason_codes
    by_id = {product.id: product for product in catalog}
    assert all(holding.amount * (1 + by_id[holding.product_id].expected_return * by_id[holding.product_id].term_months / 12) <= 500_000 + 1e-9 for holding in fixed if by_id[holding.product_id].kind in {"deposit", "large_cd"})
    full_catalog = load_catalog(Path(__file__).parents[1] / "src" / "wealth_advisor" / "data" / "products_cn.json")
    short = build_allocation(100_000, 1, full_catalog, horizon_years=1, liquidity_days=1)
    assert all(next(product for product in full_catalog if product.id == holding.product_id).kind == "fund" for holding in short.holdings)


def test_fixed_income_is_flat_in_stress_and_grows_at_rate_in_rehearsal():
    product = next(product for product in load_fixed_income_cn() if product.kind == "deposit")
    allocation = Allocation(1, 100_000, (Holding(product.id, "cash", 1.0, 100_000, ()),), product.expected_return, 0.0, 0.0, 0.0, {"cash": 1.0, "bonds": 0, "equity": 0, "gold": 0, "reits": 0}, (0, 0.06))
    assert stress_test(allocation).loss_percent == 0
    path = portfolio_path(allocation)
    assert path[-1].value > allocation.amount


def test_fixed_income_execution_is_at_par_without_cooling_off():
    products = load_fixed_income_cn()
    product = next(product for product in products if product.kind == "deposit" and product.term_months == 12)
    allocation = Allocation(1, 50_000, (Holding(product.id, "cash", 1.0, 50_000, ()),), product.expected_return, 0.0, 0.0, 0.0, {"cash": 1.0, "bonds": 0, "equity": 0, "gold": 0, "reits": 0}, (0, 0.06))
    account = SimulatedAccount(cash=50_000)
    profile = profile_investor(ANSWERS)
    orders = account.create_draft_orders(allocation, products, profile, max_order_amount=100_000, max_daily_order_amount=100_000, max_orders_per_session=10, cooling_off_days=7)
    assert orders[0].cooling_off_until is None
    executed = account.execute(orders[0].order_id)
    assert executed.status == "EXECUTED" and executed.amount == 50_000 and executed.settles_on == date.today()
    assert executed.units == 50_000 and executed.price == 1.0
