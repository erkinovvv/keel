import pytest

from wealth_advisor.allocation import build_allocation
from wealth_advisor.catalog import load_catalog
from wealth_advisor.monitoring import EVENTS, check_live_market, check_market


@pytest.fixture
def allocation():
    return build_allocation(100_000, 4, load_catalog())


def test_selloff_loses_value_and_drifts_from_target(allocation):
    check = check_market(allocation, "equity_selloff", loss_limit=0.2)
    assert check.value_after < check.value_before and check.change < 0
    assert abs(sum(check.weights_now.values()) - 1) < 1e-9
    assert check.within_limit is True


def test_rebalance_trades_net_to_zero(allocation):
    check = check_market(allocation, "equity_selloff")
    if check.rebalance_needed:
        sells = sum(t.amount for t in check.trades if t.side == "sell")
        buys = sum(t.amount for t in check.trades if t.side == "buy")
        assert sells == pytest.approx(buys, rel=0.05)
        assert any(t.side == "buy" and t.asset_class == "equity" for t in check.trades)


def test_breached_limit_asks_for_a_risk_review(allocation):
    check = check_market(allocation, "equity_selloff", loss_limit=0.01)
    assert check.recommendation == "review_risk" and "LOSS_LIMIT_BREACHED" in check.reason_codes


def test_rehearsal_context_is_reported(allocation):
    check = check_market(allocation, "equity_selloff", rehearsal={"action": "sell", "drawdown_at_decision": 0.5})
    assert check.rehearsal_sold_at == 0.5 and "BEFORE_REHEARSAL_SELL_POINT" in check.reason_codes


def test_unknown_event_is_rejected(allocation):
    with pytest.raises(ValueError):
        check_market(allocation, "meteor")


def test_events_cover_every_asset_class():
    for spec in EVENTS.values():
        assert set(spec["returns"]) == {"cash", "bonds", "equity", "gold", "reits"}


def test_live_nav_check_reuses_loss_and_rebalance_policy(allocation):
    changes = {holding.product_id: -5.0 for holding in allocation.holdings}
    check = check_live_market(allocation, changes, loss_limit=0.01)
    assert check.event == "live_nav"
    assert check.change == pytest.approx(-0.05)
    assert check.recommendation == "review_risk"
    assert "LOSS_LIMIT_BREACHED" in check.reason_codes
