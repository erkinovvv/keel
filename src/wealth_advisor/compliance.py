"""Suitability and assistant-output controls for the advisory workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .allocation import Allocation
from .catalog import Product
from .profiling import InvestorProfile


DISCLAIMER = "This is educational information based on mock data, not a guarantee or personal investment advice. Past performance does not predict future results."
_UNSAFE_CLAIMS = re.compile(r"guaranteed|risk[- ]free|you\s+will\s+earn|certain\s+profit|future\s+price\s+will|no\s+way\s+(?:you\s+)?can\s+lose\s+money|you\s+cannot\s+lose\s+money", re.I)
_NUMBER = re.compile(r"(?<![A-Za-z])(?:[$€£]?\d[\d,]*(?:\.\d+)?)(?:\s*(?:%|percent|pct))?(?![A-Za-z])", re.I)


@dataclass(frozen=True)
class ComplianceResult:
    allowed: bool
    message: str
    reasons: tuple[str, ...]
    ungrounded_numbers: tuple[str, ...] = ()


def suitability_check(profile: InvestorProfile, product: Product, liquidity_days: int | None = None) -> tuple[bool, tuple[str, ...]]:
    """Enforce Cn ≤ Rn and the client's stated liquidity need."""

    reasons: list[str] = []
    if product.risk_class > profile.investor_class:
        reasons.append("RISK_CLASS_ABOVE_INVESTOR_CLASS")
    if liquidity_days is not None and liquidity_days <= 30 and product.liquidity_days > 30:
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


def _numeric_values(text: str) -> list[tuple[float, bool]]:
    values = []
    for match in _NUMBER.finditer(text):
        token = match.group(0)
        numeric = re.sub(r"[^0-9.]", "", token)
        if not numeric:
            continue
        value = float(numeric)
        is_percent = bool(re.search(r"%|percent|pct", token, re.I))
        values.append((value, is_percent))
    return values


def _equivalents(value: float, is_percent: bool) -> tuple[float, ...]:
    if is_percent:
        return (value / 100, value)
    return (value, value * 100 if abs(value) <= 1 else value)


def _is_year(value: float, is_percent: bool) -> bool:
    return not is_percent and value.is_integer() and 1900 <= value <= 2100


def _numbers_match(left: tuple[float, bool], right: tuple[float, bool]) -> bool:
    left_values = _equivalents(*left)
    right_values = _equivalents(*right)
    return any(abs(a - b) <= max(0.001, abs(b) * 0.006) for a in left_values for b in right_values)


_QUESTIONNAIRE_NUMBER_CONTEXT = re.compile(r"(?:option\s*|under_1y|1_3y|3_7y|7_10y|over_10y|within_1d|within_7d|within_30d|over_30d|3_6_months|over_6_months|over_75|50_75|25_50|under_25)", re.I)


def _is_list_number(message: str, start: int, end: int) -> bool:
    line_start = message.rfind("\n", 0, start) + 1
    prefix = message[line_start:start]
    return bool(re.fullmatch(r"\s*\d+\s*", prefix) and re.match(r"\s*[.)]", message[end:]))


def _is_questionnaire_number(message: str, start: int, end: int) -> bool:
    context = message[max(0, start - 24):min(len(message), end + 24)]
    return bool(_QUESTIONNAIRE_NUMBER_CONTEXT.search(context))


def output_guard(
    message: str,
    tool_results: Iterable[dict[str, Any]] = (),
    recommendation: bool = False,
    client_messages: Iterable[str] = (),
) -> ComplianceResult:
    """Block unsafe claims and ungrounded numbers, then add recommendation notices."""

    reasons: list[str] = []
    if _UNSAFE_CLAIMS.search(message):
        return ComplianceResult(False, "I cannot make guaranteed or risk-free claims. I can explain the model outputs, risks, fees, and stress results instead.", ("UNSAFE_CLAIM",), ())
    grounded = _numeric_values(" ".join(str(result) for result in tool_results))
    client_grounded = _numeric_values(" ".join(client_messages))
    ungrounded: list[str] = []
    for match in _NUMBER.finditer(message):
        number = _numeric_values(match.group(0))[0]
        if _is_year(*number):
            continue
        if _is_list_number(message, match.start(), match.end()) or _is_questionnaire_number(message, match.start(), match.end()):
            continue
        if any(_numbers_match(number, candidate) for candidate in grounded + client_grounded):
            continue
        ungrounded.append(match.group(0))
    if ungrounded:
        reasons.append("UNGROUNDED_NUMBER")
    if reasons:
        return ComplianceResult(
            False,
            "I can only state figures returned by the deterministic advisory tools. Please request the relevant comparison, allocation, or stress result.",
            tuple(reasons),
            tuple(ungrounded),
        )
    safe_message = message
    if recommendation:
        safe_message = f"{safe_message}\n\n{DISCLAIMER}"
    return ComplianceResult(True, safe_message, tuple(reasons), ())
