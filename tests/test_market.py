import numpy as np
import pytest

from wealth_advisor.allocation import build_allocation
from wealth_advisor.market import (
    backtest_model_portfolios,
    black_litterman_weights,
    estimate_market_parameters,
    ledoit_wolf_covariance,
    load_market_data,
)


def test_ledoit_wolf_covariance_is_symmetric_and_positive_semidefinite():
    covariance, shrinkage = ledoit_wolf_covariance(np.array([[1.0, 0.2], [0.8, 0.1], [1.2, 0.3]]))
    assert 0 <= shrinkage <= 1
    assert np.allclose(covariance, covariance.T)
    assert np.linalg.eigvalsh(covariance).min() >= -1e-12


def test_market_estimates_and_black_litterman_are_anchored():
    estimate = estimate_market_parameters(load_market_data())
    weights = black_litterman_weights(estimate, {"equity": .4, "bonds": .3, "cash": .1, "gold": .1, "reits": .1})
    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(weight >= 0 for weight in weights.values())
    assert weights["equity"] == pytest.approx(.4)


def test_market_backed_allocation_and_backtest():
    data = load_market_data()
    allocation = build_allocation(100_000, 4, market_data=data, use_black_litterman=True)
    assert sum(holding.weight for holding in allocation.holdings) == pytest.approx(1.0)
    reports = backtest_model_portfolios(data)
    assert [report["class"] for report in reports] == ["C1", "C2", "C3", "C4", "C5"]
    assert all(report["months"] > 200 for report in reports)
