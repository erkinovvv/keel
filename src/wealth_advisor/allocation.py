"""Deterministic constrained allocation and portfolio statistics."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Iterable, Mapping, Sequence

import numpy as np

from .catalog import DEPOSIT_INSURANCE_LIMIT, Product, filter_products, load_correlations, load_catalog


STRATEGIC_WEIGHTS: dict[int, dict[str, float]] = {
    1: {"cash": 0.45, "bonds": 0.45, "equity": 0.05, "gold": 0.05, "reits": 0.0},
    2: {"cash": 0.30, "bonds": 0.45, "equity": 0.10, "gold": 0.10, "reits": 0.05},
    3: {"cash": 0.15, "bonds": 0.40, "equity": 0.25, "gold": 0.10, "reits": 0.10},
    4: {"cash": 0.10, "bonds": 0.30, "equity": 0.40, "gold": 0.10, "reits": 0.10},
    5: {"cash": 0.05, "bonds": 0.20, "equity": 0.55, "gold": 0.10, "reits": 0.10},
}
EQUITY_CAPS = {1: 0.10, 2: 0.20, 3: 0.35, 4: 0.50, 5: 0.60}
MAX_PRODUCT_WEIGHT = 0.35
VOLATILITY_BANDS = {1: (0.00, 0.06), 2: (0.02, 0.09), 3: (0.04, 0.14), 4: (0.06, 0.20), 5: (0.08, 0.28)}


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
    var_95_1y_parametric: float
    strategic_weights: dict[str, float]
    volatility_band: tuple[float, float]
    reason_codes: tuple[str, ...] = ()
    stress_limit_before: float | None = None
    stress_limit_after: float | None = None

    @property
    def var_95_1y(self) -> float:
        """Backward-compatible alias for the zero-mean parametric one-year VaR."""

        return self.var_95_1y_parametric

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["holdings"] = [holding.as_dict() for holding in self.holdings]
        result["reason_codes"] = list(self.reason_codes)
        return result


def _rank(product: Product, cash_rate: float) -> float:
    net_return = product.expected_return - product.fee
    return (net_return - cash_rate) / max(product.volatility, 0.01)


def _product_weight_cap(product: Product, allow_cash_equivalent_50: bool = False) -> float:
    if allow_cash_equivalent_50 and product.asset_class == "cash" and product.risk_class == 1 and product.liquidity_days <= 2:
        return 0.50
    return MAX_PRODUCT_WEIGHT


def _select_holdings(
    products: list[Product],
    asset_class: str,
    target: float,
    amount: float,
    investor_class: int,
    cash_rate: float,
    preferred_max_liquid_days: int | None = None,
) -> list[Holding]:
    candidates = sorted(
        products,
        key=lambda product: (
            0 if preferred_max_liquid_days is not None and product.liquidity_days <= preferred_max_liquid_days else 1,
            -_rank(product, cash_rate),
            product.fee,
            product.id,
        ),
    )
    if not candidates:
        raise ValueError(f"no suitable product for asset class {asset_class}")
    allow_cash_equivalent_50 = preferred_max_liquid_days is not None
    maximum_weight = max(_product_weight_cap(product, allow_cash_equivalent_50) for product in candidates)
    selected: list[Product] = []
    count = 0
    for proposed_count in range(max(1, math.ceil(target / maximum_weight)), len(candidates) + 1):
        per_product = amount * target / proposed_count
        selected = []
        bank_keys: set[str] = set()
        for product in candidates:
            if per_product + 1e-9 < product.min_investment or target / proposed_count > _product_weight_cap(product, allow_cash_equivalent_50) + 1e-12:
                continue
            if product.max_per_person is not None and per_product > product.max_per_person + 1e-9:
                continue
            if product.kind in {"deposit", "large_cd"}:
                insured_principal = DEPOSIT_INSURANCE_LIMIT / (1 + product.expected_return * product.term_months / 12)
                if per_product > insured_principal + 1e-9 or product.issuer_key in bank_keys:
                    continue
                bank_keys.add(product.issuer_key)
            selected.append(product)
            if len(selected) == proposed_count:
                count = proposed_count
                break
        if count:
            break
    if not count:
        raise ValueError(f"amount {amount} cannot satisfy product, minimum, and deposit-insurance limits for {asset_class}")
    weights = [target / count] * count
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


def _liquidity_policy(liquidity_days: int | None) -> tuple[float, int] | None:
    if liquidity_days is None or liquidity_days > 30:
        return None
    if liquidity_days <= 1:
        return 0.30, 1
    if liquidity_days <= 7:
        return 0.20, 7
    return 0.10, 30


def _enforce_liquidity_sleeve(
    weights: dict[str, float],
    eligible_by_class: dict[str, list[Product]],
    sleeve_target: float,
    max_liquid_days: int,
) -> dict[str, float]:
    liquid_classes = {
        asset_class
        for asset_class, products in eligible_by_class.items()
        if any(product.liquidity_days <= max_liquid_days for product in products)
    }
    liquid_weight = sum(weights.get(asset_class, 0.0) for asset_class in liquid_classes)
    if liquid_weight >= sleeve_target - 1e-12:
        return weights
    destination = "cash" if "cash" in liquid_classes else next(iter(liquid_classes), None)
    if destination is None:
        raise ValueError("no suitable liquid products remain for the liquidity sleeve")
    deficit = sleeve_target - liquid_weight
    for asset_class in sorted(weights, key=lambda item: (-weights[item], item)):
        if asset_class in liquid_classes or deficit <= 1e-12:
            continue
        moved = min(weights[asset_class], deficit)
        weights[asset_class] -= moved
        deficit -= moved
    if deficit > 1e-9:
        raise ValueError("unable to fund the liquidity sleeve within the strategic weights")
    weights[destination] = weights.get(destination, 0.0) + sleeve_target - liquid_weight
    return weights


def _redistribute_missing_weight(weights: dict[str, float], eligible_by_class: dict[str, list[Product]]) -> dict[str, float]:
    """Move unavailable asset-class targets across the classes still suitable for the client."""

    missing = sum(target for asset_class, target in weights.items() if target and not eligible_by_class[asset_class])
    for asset_class in weights:
        if weights[asset_class] and not eligible_by_class[asset_class]:
            weights[asset_class] = 0.0
    if missing <= 1e-12:
        return weights
    available = [asset_class for asset_class, target in weights.items() if target > 0 and eligible_by_class[asset_class]]
    total = sum(weights[asset_class] for asset_class in available)
    if not available or total <= 1e-12:
        raise ValueError("no suitable products remain after exclusions")
    for asset_class in available:
        weights[asset_class] += missing * weights[asset_class] / total
    return weights


def _project_bounds(weights: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    """Project class weights onto box constraints and the unit-sum simplex."""

    projected = np.clip(weights, lower, upper)
    for _ in range(20):
        difference = 1.0 - float(projected.sum())
        if abs(difference) <= 1e-12:
            break
        if difference > 0:
            room = upper - projected
        else:
            room = projected - lower
        total_room = float(room.sum())
        if total_room <= 1e-12:
            break
        projected += difference * room / total_room
        projected = np.clip(projected, lower, upper)
    return projected


def _refine_class_weights(
    base_weights: dict[str, float],
    eligible_by_class: dict[str, list[Product]],
    investor_class: int,
    market_estimate: object | None = None,
    use_black_litterman: bool = False,
    bl_tau: float = 0.05,
    bl_views: Sequence[tuple[Mapping[str, float], float, float]] = (),
) -> dict[str, float]:
    """Apply a small projected-gradient mean-variance refinement around strategic weights."""

    classes, correlations = load_correlations()
    active = [asset for asset in classes if base_weights.get(asset, 0.0) > 0]
    if len(active) < 2:
        return dict(base_weights)
    index = {asset: position for position, asset in enumerate(classes)}
    if market_estimate is None:
        expected = np.array([
            max(product.expected_return - product.fee for product in eligible_by_class[asset])
            for asset in active
        ])
        class_volatility = np.array([
            min(product.volatility for product in eligible_by_class[asset])
            for asset in active
        ])
        correlation = np.array([
            [correlations[index[left]][index[right]] for right in active]
            for left in active
        ])
        covariance = correlation * np.outer(class_volatility, class_volatility)
    else:
        from .market import black_litterman_weights

        expected = np.array([market_estimate.annual_expected_returns[asset] for asset in active])
        covariance = np.array([
            [market_estimate.annual_covariance[left][right] for right in active]
            for left in active
        ])
        anchored = black_litterman_weights(market_estimate, base_weights, tau=bl_tau, views=bl_views) if use_black_litterman else None
    base = np.array([base_weights[asset] for asset in active], dtype=float)
    lower = np.maximum(0.0, base - 0.10)
    upper = np.minimum(1.0, base + 0.10)
    if "cash" in active:
        lower[active.index("cash")] = max(lower[active.index("cash")], 0.05)
    if "equity" in active:
        upper[active.index("equity")] = min(upper[active.index("equity")], EQUITY_CAPS[investor_class])
    if market_estimate is not None and anchored is not None:
        anchored_weights = np.array([anchored.get(asset, 0.0) for asset in active])
        anchored_weights /= anchored_weights.sum()
        base = _project_bounds(anchored_weights, lower, upper)
    target_min, target_max = VOLATILITY_BANDS[investor_class]

    def score(weights: np.ndarray) -> float:
        variance = float(weights @ covariance @ weights)
        volatility = math.sqrt(max(variance, 0.0))
        band_penalty = max(0.0, target_min - volatility) ** 2 + max(0.0, volatility - target_max) ** 2
        return float(weights @ expected - 0.75 * variance - 4.0 * band_penalty)

    weights = base.copy()
    for _ in range(40):
        gradient = expected - 1.5 * (covariance @ weights)
        candidate = _project_bounds(weights + 0.15 * gradient, lower, upper)
        if score(candidate) <= score(weights) + 1e-12:
            break
        weights = candidate
    return {asset: float(weights[position]) for position, asset in enumerate(active)} | {
        asset: float(base_weights.get(asset, 0.0)) for asset in classes if asset not in active
    }


def _worst_stress_loss_holdings(holdings: Sequence[Holding], catalog_by_id: Mapping[str, Product]) -> float:
    from .stress import SCENARIOS

    return max(
        max(
            0.0,
            -sum(
                holding.weight
                * (0.0 if catalog_by_id[holding.product_id].kind in {"deposit", "large_cd", "savings_bond"} else shocks[holding.asset_class])
                for holding in holdings
            ),
        )
        for shocks in SCENARIOS.values()
    )


def _worst_stress_loss(weights: dict[str, float]) -> float:
    """Return the class-level stress loss used while moving strategic weights."""

    from .stress import SCENARIOS

    return max(max(0.0, -sum(weight * shocks[asset] for asset, weight in weights.items())) for shocks in SCENARIOS.values())


def _constrain_stress_weights(
    weights: dict[str, float],
    strategic: dict[str, float],
    limit: float,
) -> dict[str, float]:
    from .stress import SCENARIOS

    adjusted = dict(weights)
    for _ in range(20):
        worst = max(SCENARIOS.values(), key=lambda shocks: -sum(weight * shocks[asset] for asset, weight in adjusted.items()))
        excess = _worst_stress_loss(adjusted) - limit
        if excess <= 1e-10:
            break
        for source in ("reits", "equity"):
            source_room = max(0.0, adjusted.get(source, 0.0) - max(0.0, strategic.get(source, 0.0) - 0.10))
            for destination in ("cash", "bonds"):
                destination_room = max(0.0, min(1.0, strategic.get(destination, 0.0) + 0.10) - adjusted.get(destination, 0.0))
                improvement = worst[destination] - worst[source]
                if improvement <= 0 or source_room <= 1e-12 or destination_room <= 1e-12:
                    continue
                moved = min(source_room, destination_room, excess / improvement)
                adjusted[source] -= moved
                adjusted[destination] += moved
                source_room -= moved
                excess -= moved * improvement
                if excess <= 1e-10:
                    break
            if excess <= 1e-10:
                break
    return adjusted


def build_allocation(
    amount: float,
    investor_class: int,
    products: Iterable[Product] | None = None,
    *,
    liquidity_days: int | None = None,
    exclusions: Iterable[str] = (),
    cash_rate: float = 0.035,
    max_tolerable_loss: float | None = None,
    market_data: object | None = None,
    use_black_litterman: bool = False,
    bl_tau: float = 0.05,
    bl_views: Sequence[tuple[Mapping[str, float], float, float]] = (),
    horizon_years: int | None = None,
) -> Allocation:
    """Build a suitable portfolio with non-negative weights and a 35% product cap."""

    if amount <= 0:
        raise ValueError("amount must be positive")
    if investor_class not in STRATEGIC_WEIGHTS:
        raise ValueError("investor_class must be between 1 and 5")
    if max_tolerable_loss is not None and not 0 <= max_tolerable_loss <= 1:
        raise ValueError("max_tolerable_loss must be between 0 and 1")
    if use_black_litterman and market_data is None:
        raise ValueError("market_data is required for Black-Litterman allocation")
    catalog = list(products) if products is not None else load_catalog()
    excluded = tuple(exclusions)
    strategic = dict(STRATEGIC_WEIGHTS[investor_class])
    if strategic["equity"] > EQUITY_CAPS[investor_class]:
        strategic["equity"] = EQUITY_CAPS[investor_class]
    liquidity_policy = _liquidity_policy(liquidity_days)
    max_liquid_days = liquidity_policy[1] if liquidity_policy else None
    eligible_by_class = {
        asset_class: [
            product
            for product in filter_products(catalog, investor_class, amount=amount, liquidity_days=None, exclusions=excluded, horizon_years=horizon_years)
            if max_liquid_days is None or product.liquidity_days <= 30
            if product.asset_class == asset_class
        ]
        for asset_class in strategic
    }
    strategic = _redistribute_missing_weight(strategic, eligible_by_class)
    if liquidity_policy:
        strategic = _enforce_liquidity_sleeve(strategic, eligible_by_class, *liquidity_policy)
    class_base = dict(strategic)
    market_estimate = None
    if market_data is not None:
        from .market import estimate_market_parameters

        market_estimate = estimate_market_parameters(market_data)
    strategic = _refine_class_weights(strategic, eligible_by_class, investor_class, market_estimate, use_black_litterman, bl_tau, bl_views)
    if liquidity_policy:
        strategic = _enforce_liquidity_sleeve(strategic, eligible_by_class, *liquidity_policy)
    catalog_by_id = {product.id: product for product in catalog}

    def selected_holdings(weights: dict[str, float]) -> list[Holding]:
        preview: list[Holding] = []
        for asset_class, target in weights.items():
            if target:
                preview.extend(
                    _select_holdings(
                        eligible_by_class[asset_class], asset_class, target, amount, investor_class, cash_rate,
                        max_liquid_days if liquidity_policy and asset_class == "cash" else None,
                    )
                )
        return preview

    def stress_for_weights(weights: dict[str, float]) -> float:
        return _worst_stress_loss_holdings(selected_holdings(weights), catalog_by_id)

    stress_before = stress_for_weights(strategic) if max_tolerable_loss is not None else None
    if max_tolerable_loss is not None and stress_before > max_tolerable_loss + 1e-10:
        strategic = _constrain_stress_weights(strategic, class_base, max_tolerable_loss)
        if liquidity_policy:
            strategic = _enforce_liquidity_sleeve(strategic, eligible_by_class, *liquidity_policy)
        if stress_for_weights(strategic) > max_tolerable_loss + 1e-10:
            if investor_class == 1:
                raise ValueError("no suitable allocation satisfies the client's maximum historical stress loss")
            lower = build_allocation(
                amount, investor_class - 1, catalog, liquidity_days=liquidity_days,
                exclusions=excluded, cash_rate=cash_rate, max_tolerable_loss=max_tolerable_loss,
                market_data=market_data, use_black_litterman=use_black_litterman,
                bl_tau=bl_tau, bl_views=bl_views,
                horizon_years=horizon_years,
            )
            return replace(
                lower,
                reason_codes=("STRESS_LIMIT_APPLIED",),
                stress_limit_before=stress_before,
                stress_limit_after=_worst_stress_loss_holdings(
                    lower.holdings,
                    {product.id: product for product in catalog},
                ),
            )
    holdings: list[Holding] = []
    for asset_class, target in strategic.items():
        if target:
            holdings.extend(
                _select_holdings(
                    eligible_by_class[asset_class],
                    asset_class,
                    target,
                    amount,
                    investor_class,
                    cash_rate,
                    max_liquid_days if liquidity_policy and asset_class == "cash" else None,
                )
            )
    if liquidity_policy:
        sleeve_target, max_liquid_days = liquidity_policy
        catalog_by_id = {product.id: product for product in catalog}
        holdings = [
            Holding(
                holding.product_id,
                holding.asset_class,
                holding.weight,
                holding.amount,
                holding.reason_codes + (("LIQUIDITY_SLEEVE",) if catalog_by_id[holding.product_id].liquidity_days <= max_liquid_days else ()),
            )
            for holding in holdings
        ]
    deposit_total = sum(holding.amount for holding in holdings if next(product for product in catalog if product.id == holding.product_id).kind in {"deposit", "large_cd"})
    insurance_split = deposit_total > 500_000
    if insurance_split:
        by_id = {product.id: product for product in catalog}
        holdings = [
            replace(holding, reason_codes=holding.reason_codes + ("DEPOSIT_INSURANCE_SPLIT",))
            if by_id[holding.product_id].kind in {"deposit", "large_cd"} else holding
            for holding in holdings
        ]
    stress_applied = max_tolerable_loss is not None and stress_before is not None and stress_before > max_tolerable_loss + 1e-10
    if stress_applied:
        holdings = [
            Holding(holding.product_id, holding.asset_class, holding.weight, holding.amount, holding.reason_codes + ("STRESS_LIMIT_APPLIED",))
            for holding in holdings
        ]
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
        var_95_1y_parametric=float(1.645 * portfolio_volatility * amount),
        strategic_weights={asset: float(weight) for asset, weight in zip(classes, class_weights)},
        volatility_band=VOLATILITY_BANDS[investor_class],
        reason_codes=tuple(code for code, active in (("STRESS_LIMIT_APPLIED", stress_applied), ("DEPOSIT_INSURANCE_SPLIT", insurance_split)) if active),
        stress_limit_before=stress_before if stress_applied else None,
        stress_limit_after=_worst_stress_loss_holdings(holdings, by_id) if stress_applied else None,
    )
