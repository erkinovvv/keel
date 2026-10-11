"""Real-data portfolio estimation, Black-Litterman weights, and backtests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


ASSET_CLASSES = ("equity", "bonds", "cash", "gold", "reits")
DATA_PATH = Path(__file__).parents[2] / "data" / "market" / "returns.json"


@dataclass(frozen=True)
class MarketData:
    months: tuple[str, ...]
    asset_classes: tuple[str, ...]
    returns: np.ndarray
    sources: tuple[dict[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.returns.ndim != 2 or self.returns.shape != (len(self.months), len(self.asset_classes)):
            raise ValueError("market returns must match months and asset classes")
        if tuple(self.asset_classes) != ASSET_CLASSES:
            raise ValueError(f"market assets must be {ASSET_CLASSES}")

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "MarketData":
        assets = tuple(raw.get("asset_classes", ASSET_CLASSES))
        rows = raw.get("returns", [])
        months = tuple(row["month"] for row in rows)
        matrix = np.array([[row[asset] for asset in assets] for row in rows], dtype=float)
        sources = tuple(raw.get("sources", ()))
        return cls(months, assets, matrix, sources)

    def as_dict(self) -> dict[str, object]:
        return {
            "asset_classes": list(self.asset_classes),
            "months": list(self.months),
            "returns": [
                {"month": month, **{asset: float(value) for asset, value in zip(self.asset_classes, row)}}
                for month, row in zip(self.months, self.returns)
            ],
            "sources": list(self.sources),
        }


@dataclass(frozen=True)
class MarketEstimate:
    observations: int
    annual_expected_returns: dict[str, float]
    annual_covariance: dict[str, dict[str, float]]
    shrinkage: float


def load_market_data(path: str | Path | None = None) -> MarketData:
    market_path = Path(path) if path else DATA_PATH
    return MarketData.from_dict(json.loads(market_path.read_text(encoding="utf-8")))


def ledoit_wolf_covariance(returns: np.ndarray | Sequence[Sequence[float]]) -> tuple[np.ndarray, float]:
    """Estimate a positive-definite covariance matrix with diagonal shrinkage."""

    observations = np.asarray(returns, dtype=float)
    if observations.ndim != 2 or observations.shape[0] < 2:
        raise ValueError("at least two return observations are required")
    centered = observations - observations.mean(axis=0)
    sample = centered.T @ centered / observations.shape[0]
    target = np.eye(observations.shape[1]) * np.trace(sample) / observations.shape[1]
    delta = float(np.square(sample - target).sum())
    if delta <= 1e-18:
        return target, 1.0
    outer_products = np.einsum("ni,nj->nij", centered, centered)
    beta = float(np.square(outer_products - sample).sum(axis=(1, 2)).mean() / observations.shape[0])
    shrinkage = min(1.0, max(0.0, beta / delta))
    covariance = (1.0 - shrinkage) * sample + shrinkage * target
    return covariance, shrinkage


def estimate_market_parameters(data: MarketData) -> MarketEstimate:
    covariance, shrinkage = ledoit_wolf_covariance(data.returns)
    expected = data.returns.mean(axis=0) * 12
    annual_covariance = covariance * 12
    return MarketEstimate(
        observations=len(data.months),
        annual_expected_returns={asset: float(value) for asset, value in zip(data.asset_classes, expected)},
        annual_covariance={
            left: {right: float(annual_covariance[i, j]) for j, right in enumerate(data.asset_classes)}
            for i, left in enumerate(data.asset_classes)
        },
        shrinkage=shrinkage,
    )


def black_litterman_weights(
    estimate: MarketEstimate,
    strategic_weights: Mapping[str, float],
    *,
    risk_aversion: float = 3.0,
    views: Sequence[tuple[Mapping[str, float], float, float]] = (),
) -> dict[str, float]:
    """Return non-negative BL weights, with the strategic mix as the market prior.

    Each view is ``(asset exposures, expected return, uncertainty variance)``. With
    no views, the posterior is the reverse-optimised strategic prior.
    """

    assets = tuple(estimate.annual_expected_returns)
    covariance = np.array([[estimate.annual_covariance[left][right] for right in assets] for left in assets])
    prior_weights = np.array([float(strategic_weights.get(asset, 0.0)) for asset in assets])
    prior_weights = np.maximum(prior_weights, 0.0)
    prior_weights /= prior_weights.sum()
    prior_return = risk_aversion * covariance @ prior_weights
    posterior = prior_return.copy()
    if views:
        prior_precision = np.linalg.pinv(covariance)
        for exposure, view_return, uncertainty in views:
            vector = np.array([float(exposure.get(asset, 0.0)) for asset in assets])
            view_precision = np.outer(vector, vector) / max(float(uncertainty), 1e-8)
            posterior = np.linalg.pinv(prior_precision + view_precision) @ (
                prior_precision @ posterior + vector * float(view_return) / max(float(uncertainty), 1e-8)
            )
    weights = np.linalg.pinv(covariance) @ posterior / max(risk_aversion, 1e-8)
    weights = np.maximum(weights, 0.0)
    if weights.sum() <= 1e-12:
        weights = prior_weights
    else:
        weights /= weights.sum()
    return {asset: float(weight) for asset, weight in zip(assets, weights)}


def backtest_model_portfolios(data: MarketData) -> list[dict[str, object]]:
    """Backtest static C1–C5 strategic mixes from the first available month onward."""

    from .allocation import STRATEGIC_WEIGHTS, VOLATILITY_BANDS

    reports: list[dict[str, object]] = []
    for investor_class, strategic in STRATEGIC_WEIGHTS.items():
        weights = np.array([strategic.get(asset, 0.0) for asset in data.asset_classes])
        series = data.returns @ weights
        wealth = np.cumprod(1.0 + series)
        peaks = np.maximum.accumulate(wealth)
        drawdowns = 1.0 - wealth / peaks
        tolerance = VOLATILITY_BANDS[investor_class][1]
        reports.append({
            "class": f"C{investor_class}",
            "months": len(series),
            "start": data.months[0],
            "end": data.months[-1],
            "realised_volatility": float(series.std(ddof=1) * np.sqrt(12)),
            "max_drawdown": float(drawdowns.max(initial=0.0)),
            "drawdown_tolerance": tolerance,
            "drawdown_within_tolerance": bool(drawdowns.max(initial=0.0) <= tolerance + 1e-12),
        })
    return reports

