"""Mock product catalog and deterministic comparison calculations."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


DATA_DIR = Path(__file__).parent / "data"
DEPOSIT_INSURANCE_LIMIT = 500_000.0


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
    kind: str = "fund"
    issuer: str | None = None
    issuer_zh: str | None = None
    issuer_key: str | None = None
    name_zh: str | None = None
    term_months: int | None = None
    max_per_person: float | None = None
    sale_from: str | None = None
    sale_to: str | None = None
    promo: bool = False

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
    kind: str = "fund"
    rate: float | None = None
    term_months: int | None = None
    early_withdrawal_cost_6m: float | None = None
    insured: bool | None = None

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
    if catalog_path.name == "products_cn.json":
        products.extend(load_fixed_income_cn())
    if not products or any(product.risk_class not in range(1, 6) for product in products):
        raise ValueError("catalog must contain products with risk classes R1-R5")
    return products


def load_fixed_income_cn(path: str | Path | None = None) -> list[Product]:
    """Expand pooled state-bank rate rows into separate insured bank offers."""

    data = json.loads((Path(path) if path else DATA_DIR / "fixed_income_cn.json").read_text(encoding="utf-8"))
    banks = (("icbc", "ICBC", "工商银行"), ("ccb", "CCB", "建设银行"), ("abc", "ABC", "农业银行"), ("boc", "BOC", "中国银行"), ("bocom", "BoCom", "交通银行"))
    products: list[Product] = []
    for row in data["products"]:
        issuers = banks if "big6" in row["id"] else ((row["id"].split("-")[1] if row["kind"] != "savings_bond" else "mof", row["issuer"], row["issuer_zh"]),)
        for issuer_key, issuer_en, issuer_zh in issuers:
            kind = row["kind"]
            months = row["term_months"]
            product_id = row["id"].replace("big6", issuer_key)
            name_en = f"{issuer_en} {months}-month {'savings bond' if kind == 'savings_bond' else 'large CD' if kind == 'large_cd' else 'deposit'}"
            products.append(Product(
                id=product_id, name=name_en, asset_class="bonds" if kind == "savings_bond" else "cash",
                region="CN", risk_class=1, expected_return=row["rate"], volatility=0.0,
                fee=0.0, liquidity_days=months * 30, min_investment=row["min_amount"], nav=1.0,
                kind=kind, issuer=issuer_en, issuer_zh=issuer_zh, issuer_key=issuer_key, name_zh=f"{issuer_zh} {months}个月",
                term_months=months, max_per_person=row.get("max_per_person"),
                sale_from=row.get("sale_from"), sale_to=row.get("sale_to"), promo=row["promo"],
            ))
    return products


def fixed_income_available(product: Product, today: date | None = None) -> bool:
    today = today or date.today()
    return product.sale_from is None or date.fromisoformat(product.sale_from) <= today <= date.fromisoformat(product.sale_to)


def early_withdrawal_value(product: Product, amount: float, months_held: float) -> float:
    """Value an early redemption using the dated snapshot's stated interest/fee rules."""

    if product.kind not in {"deposit", "large_cd", "savings_bond"} or amount < 0 or months_held < 0:
        raise ValueError("a fixed-income product, nonnegative amount and holding period are required")
    if months_held >= product.term_months:
        return amount * (1 + product.expected_return * product.term_months / 12)
    if product.kind in {"deposit", "large_cd"}:
        return amount * (1 + 0.0005 * months_held / 12)
    if months_held < 6:
        interest = 0.0
    else:
        days_deducted = 180 if months_held < 24 else 90 if months_held < 36 else 60
        interest = amount * product.expected_return * max(0.0, months_held / 12 - days_deducted / 365)
    return amount + interest - amount * 0.001


def filter_products(
    products: Iterable[Product],
    investor_class: int,
    amount: float = 0.0,
    liquidity_days: int | None = None,
    asset_class: str | None = None,
    exclusions: Iterable[str] = (),
    horizon_years: int | None = None,
    kind: str | None = None,
    today: date | None = None,
) -> list[Product]:
    """Return products satisfying suitability, liquidity, amount, and exclusions."""

    excluded = {item.upper() for item in exclusions}
    return [
        product
        for product in products
        if product.risk_class <= investor_class
        and (not amount or product.min_investment <= amount)
        and (liquidity_days is None or product.liquidity_days <= liquidity_days or product.kind != "fund")
        and (asset_class is None or product.asset_class == asset_class)
        and (kind is None or product.kind == kind)
        and (horizon_years is None or product.term_months is None or product.term_months <= horizon_years * 12)
        and fixed_income_available(product, today)
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
    kind: str | None = None,
    today: date | None = None,
) -> list[ProductComparison]:
    """Compare suitable products using net return and compounded fee drag."""

    if amount <= 0 or horizon_years <= 0:
        raise ValueError("amount and horizon_years must be positive")
    comparisons = []
    selected_kind = kind or (asset_class if asset_class in {"deposit", "large_cd", "savings_bond"} else None)
    selected_asset = None if selected_kind and asset_class in {"deposit", "large_cd", "savings_bond"} else asset_class
    for product in filter_products(products, investor_class, amount, liquidity_days, selected_asset, exclusions, horizon_years, selected_kind, today):
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
                kind=product.kind,
                rate=product.expected_return if product.kind != "fund" else None,
                term_months=product.term_months,
                early_withdrawal_cost_6m=(amount * (1 + product.expected_return * 0.5) - early_withdrawal_value(product, amount, 6)) if product.kind != "fund" else None,
                insured=(amount * (1 + product.expected_return * product.term_months / 12) <= DEPOSIT_INSURANCE_LIMIT) if product.kind in {"deposit", "large_cd"} else None,
            )
        )
    return sorted(comparisons, key=lambda item: (-item.sharpe_like, item.fee, item.product_id))


def load_correlations(path: str | Path | None = None) -> tuple[list[str], list[list[float]]]:
    """Load the fixed asset-class correlation matrix used by allocation math."""

    matrix = json.loads((Path(path) if path else DATA_DIR / "correlations.json").read_text(encoding="utf-8"))
    return matrix["asset_classes"], matrix["matrix"]
