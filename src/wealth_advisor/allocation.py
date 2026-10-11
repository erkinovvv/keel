"""Deterministic constrained allocation and portfolio statistics."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np

from .catalog import Product, filter_products, load_correlations, load_catalog


STRATEGIC_WEIGHTS: dict[int, dict[str, float]] = {
    1: {"cash": 0.45, "bonds": 0.45, "equity": 0.05, "gold": 0.05, "reits": 0.0},
    2: {"cash": 0.30, "bonds": 0.45, "equity": 0.10, "gold": 0.10, "reits": 0.05},
    3: {"cash": 0.15, "bonds": 0.40, "equity": 0.25, "gold": 0.10, "reits": 0.10},
    4: {"cash": 0.10, "bonds": 0.30, "equity": 0.40, "gold": 0.10, "reits": 0.10},
    5: {"cash": 0.05, "bonds": 0.20, "equity": 0.55, "gold": 0.10, "reits": 0.10},
}
EQUITY_CAPS = {1: 0.10, 2: 0.20, 3: 0.35, 4: 0.50, 5: 0.60}
MAX_PRODUCT_WEIGHT = 0.35


@dataclass(frozen=True)
class Holding:
    product_id: str
    asset_class: str
    weight: float
    amount: float
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["reason_codes"] = list(self.reason_codes)
        return result


@dataclass(frozen=True)
class Allocation:
    investor_class: int
    amount: float
    holdings: tuple[Holding, ...]
    expected_return: float
    volatility: float
    fee: float
    var_95_1y: float
    strategic_weights: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["holdings"] = [holding.as_dict() for holding in self.holdings]
        return result


def _rank(product: Product, cash_rate: float) -> float:
    net_return = product.expected_return - product.fee
    return (net_return - cash_rate) / max(product.volatility, 0.01)


def _select_holdings(products: list[Product], asset_class: str, target: float, amount: float, investor_class: int, cash_rate: float) -> list[Holding]:
    candidates = sorted(
        products,
        key=lambda product: (-_rank(product, cash_rate), product.fee, product.id),
    )
    if not candidates:
        raise ValueError(f"no suitable product for asset class {asset_class}")
    count = max(1, math.ceil(target / MAX_PRODUCT_WEIGHT))
    eligible = [product for product in candidates if amount * target / count >= product.min_investment]
    if len(eligible) < count:
        raise ValueError(f"amount {amount} cannot satisfy the {MAX_PRODUCT_WEIGHT:.0%} product cap for {asset_class}")
    if not eligible:
        raise ValueError(f"amount {amount} is too small for {asset_class} minimum investment")
    selected = eligible[:count]
    weights: list[float] = []
    remaining = target
    for _ in selected:
        weight = min(MAX_PRODUCT_WEIGHT, remaining)
        weights.append(weight)
        remaining -= weight
    return [
        Holding(
            product_id=product.id,
            asset_class=asset_class,
            weight=weight,
            amount=amount * weight,
            reason_codes=(f"SUITABLE_C{investor_class}_R{product.risk_class}", "RISK_ADJUSTED_RETURN_NET_OF_FEES"),
        )
        for product, weight in zip(selected, weights)
    ]


def build_allocation(
    amount: float,
    investor_class: int,
    products: Iterable[Product] | None = None,
    *,
    liquidity_days: int | None = None,
    exclusions: Iterable[str] = (),
    cash_rate: float = 0.035,
) -> Allocation:
    """Build a suitable portfolio with non-negative weights and a 35% product cap."""

    if amount <= 0:
        raise ValueError("amount must be positive")
    if investor_class not in STRATEGIC_WEIGHTS:
        raise ValueError("investor_class must be between 1 and 5")
    catalog = list(products) if products is not None else load_catalog()
    strategic = dict(STRATEGIC_WEIGHTS[investor_class])
    if strategic["equity"] > EQUITY_CAPS[investor_class]:
        strategic["equity"] = EQUITY_CAPS[investor_class]
    eligible_by_class = {
        asset_class: [
            product
            for product in filter_products(catalog, investor_class, amount=amount, liquidity_days=liquidity_days, exclusions=exclusions)
            if product.asset_class == asset_class
        ]
        for asset_class in strategic
    }
    missing_weight = 0.0
    for asset_class, target in list(strategic.items()):
        if target and not eligible_by_class[asset_class]:
            missing_weight += target
            strategic[asset_class] = 0.0
    if missing_weight:
        for fallback in ("cash", "bonds", "gold", "reits", "equity"):
            if eligible_by_class[fallback]:
                strategic[fallback] += missing_weight
                break
        else:
            raise ValueError("no suitable products remain after exclusions")
    holdings: list[Holding] = []
    for asset_class, target in strategic.items():
        if target:
            holdings.extend(_select_holdings(eligible_by_class[asset_class], asset_class, target, amount, investor_class, cash_rate))
    total_weight = sum(holding.weight for holding in holdings)
    if not math.isclose(total_weight, 1.0, abs_tol=1e-9):
        raise ValueError(f"allocation weights sum to {total_weight}")
    by_id = {product.id: product for product in catalog}
    classes, correlations = load_correlations()
    class_index = {asset_class: index for index, asset_class in enumerate(classes)}
    returns = np.array([by_id[h.product_id].expected_return - by_id[h.product_id].fee for h in holdings])
    volatility = np.array([by_id[h.product_id].volatility for h in holdings])
    weights = np.array([h.weight for h in holdings])
    class_weights = np.array([sum(h.weight for h in holdings if h.asset_class == asset) for asset in classes])
    covariance = np.diag(volatility)
    for left, left_holding in enumerate(holdings):
        for right, right_holding in enumerate(holdings):
            correlation = correlations[class_index[left_holding.asset_class]][class_index[right_holding.asset_class]]
            covariance[left, right] = correlation * volatility[left] * volatility[right]
    portfolio_volatility = float(math.sqrt(max(0.0, weights @ covariance @ weights)))
    return Allocation(
        investor_class=investor_class,
        amount=amount,
        holdings=tuple(holdings),
        expected_return=float(weights @ returns),
        volatility=portfolio_volatility,
        fee=float(sum(h.weight * by_id[h.product_id].fee for h in holdings)),
        var_95_1y=float(1.645 * portfolio_volatility * amount),
        strategic_weights={asset: float(weight) for asset, weight in zip(classes, class_weights)},
    )
