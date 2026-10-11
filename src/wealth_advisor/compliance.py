"""Suitability and assistant-output controls for the advisory workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .allocation import Allocation
from .catalog import Product
from .profiling import InvestorProfile


DISCLAIMER = "This is educational information based on mock data, not a guarantee or personal investment advice. Past performance does not predict future results."
_UNSAFE_CLAIMS = re.compile(r"guaranteed|risk[- ]free|you\s+will\s+earn|certain\s+profit|future\s+price\s+will", re.I)
_NUMBER = re.compile(r"(?<![A-Za-z])(?:\$|€|£)?\d[\d,.]*(?:%|\b)")


@dataclass(frozen=True)
class ComplianceResult:
    allowed: bool
    message: str
    reasons: tuple[str, ...]


def suitability_check(profile: InvestorProfile, product: Product, liquidity_days: int | None = None) -> tuple[bool, tuple[str, ...]]:
    """Enforce Cn ≤ Rn and the client's stated liquidity need."""

    reasons: list[str] = []
    if product.risk_class > profile.investor_class:
        reasons.append("RISK_CLASS_ABOVE_INVESTOR_CLASS")
    if liquidity_days is not None and product.liquidity_days > liquidity_days:
        reasons.append("LIQUIDITY_HORIZON_MISMATCH")
    return not reasons, tuple(reasons)


def pretrade_check(
    profile: InvestorProfile,
    allocation: Allocation,
    products: Iterable[Product],
    cash_available: float,
) -> tuple[bool, tuple[str, ...]]:
    """Check all holdings before allowing a simulated draft order."""

    by_id = {product.id: product for product in products}
    reasons: list[str] = []
    if allocation.amount > cash_available:
        reasons.append("INSUFFICIENT_CASH")
    if sum(holding.weight for holding in allocation.holdings) > 1.000001:
        reasons.append("WEIGHTS_EXCEED_ONE")
    for holding in allocation.holdings:
        product = by_id[holding.product_id]
        suitable, product_reasons = suitability_check(profile, product, profile.liquidity_days)
        if not suitable:
            reasons.extend(product_reasons)
        if holding.amount + 1e-9 < product.min_investment:
            reasons.append(f"MIN_INVESTMENT_{product.id}")
    return not reasons, tuple(sorted(set(reasons)))


def _tool_numbers(tool_results: Iterable[dict[str, Any]]) -> set[str]:
    text = " ".join(str(result) for result in tool_results)
    return {token.replace(",", "") for token in _NUMBER.findall(text)}


def output_guard(message: str, tool_results: Iterable[dict[str, Any]] = (), recommendation: bool = False) -> ComplianceResult:
    """Block unsafe claims and ungrounded numbers, then add recommendation notices."""

    reasons: list[str] = []
    if _UNSAFE_CLAIMS.search(message):
        return ComplianceResult(False, "I cannot make guaranteed or risk-free claims. I can explain the model outputs, risks, fees, and stress results instead.", ("UNSAFE_CLAIM",))
    grounded = _tool_numbers(tool_results)
    for number in _NUMBER.findall(message):
        if number.replace(",", "") not in grounded:
            reasons.append("UNGROUNDED_NUMBER")
            break
    if reasons:
        return ComplianceResult(False, "I can only state figures returned by the deterministic advisory tools. Please request the relevant comparison, allocation, or stress result.", tuple(reasons))
    safe_message = message
    if recommendation:
        safe_message = f"{safe_message}\n\n{DISCLAIMER}"
    return ComplianceResult(True, safe_message, tuple(reasons))

