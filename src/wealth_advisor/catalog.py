"""Mock product catalog and deterministic comparison calculations."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    asset_class: str
    region: str
    risk_class: int
    expected_return: float
    volatility: float
    fee: float
    liquidity_days: int
    min_investment: float
    nav: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProductComparison:
    product_id: str
    name: str
    asset_class: str
    risk_class: int
    expected_return: float
    volatility: float
    fee: float
    net_return: float
    sharpe_like: float
    fee_drag: float
    liquidity_days: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def load_catalog(path: str | Path | None = None) -> list[Product]:
    """Load and validate the product catalog used by every calculation."""

    # WEALTH_ADVISOR_CATALOG=cn selects real Chinese public funds (scripts/build_cn_catalog.py);
    # the default mock catalog keeps tests deterministic.
    default = "products_cn.json" if os.getenv("WEALTH_ADVISOR_CATALOG", "").lower() == "cn" else "products.json"
    catalog_path = Path(path) if path else DATA_DIR / default
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    products = [Product(**item) for item in raw]
    if not products or any(product.risk_class not in range(1, 6) for product in products):
        raise ValueError("catalog must contain products with risk classes R1-R5")
    return products


def filter_products(
    products: Iterable[Product],
    investor_class: int,
    amount: float = 0.0,
    liquidity_days: int | None = None,
    asset_class: str | None = None,
    exclusions: Iterable[str] = (),
) -> list[Product]:
    """Return products satisfying suitability, liquidity, amount, and exclusions."""

    excluded = {item.upper() for item in exclusions}
    return [
        product
        for product in products
        if product.risk_class <= investor_class
        and (not amount or product.min_investment <= amount)
        and (liquidity_days is None or product.liquidity_days <= liquidity_days)
        and (asset_class is None or product.asset_class == asset_class)
        and product.id.upper() not in excluded
        and product.asset_class.upper() not in excluded
        and product.region.upper() not in excluded
    ]


def compare_products(
    products: Iterable[Product],
    amount: float,
    horizon_years: int,
    investor_class: int,
    cash_rate: float = 0.035,
    liquidity_days: int | None = None,
    asset_class: str | None = None,
    exclusions: Iterable[str] = (),
) -> list[ProductComparison]:
    """Compare suitable products using net return and compounded fee drag."""

    if amount <= 0 or horizon_years <= 0:
        raise ValueError("amount and horizon_years must be positive")
    comparisons = []
    for product in filter_products(products, investor_class, amount, liquidity_days, asset_class, exclusions):
        net_return = product.expected_return - product.fee
        sharpe_like = (net_return - cash_rate) / product.volatility if product.volatility else 0.0
        fee_drag = amount * (1 - (1 - product.fee) ** horizon_years)
        comparisons.append(
            ProductComparison(
                product_id=product.id,
                name=product.name,
                asset_class=product.asset_class,
                risk_class=product.risk_class,
                expected_return=product.expected_return,
                volatility=product.volatility,
                fee=product.fee,
                net_return=net_return,
                sharpe_like=sharpe_like,
                fee_drag=fee_drag,
                liquidity_days=product.liquidity_days,
            )
        )
    return sorted(comparisons, key=lambda item: (-item.sharpe_like, item.fee, item.product_id))


def load_correlations(path: str | Path | None = None) -> tuple[list[str], list[list[float]]]:
    """Load the fixed asset-class correlation matrix used by allocation math."""

    matrix = json.loads((Path(path) if path else DATA_DIR / "correlations.json").read_text(encoding="utf-8"))
    return matrix["asset_classes"], matrix["matrix"]

