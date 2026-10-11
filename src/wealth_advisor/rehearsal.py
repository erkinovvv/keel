"""Crash Rehearsal: stress-test the investor, not just the portfolio.

Before money is invested, the client lives through 2008–2013 with their own proposed portfolio,
month by month on real historical returns, and can sell at any point. Where they actually sell
reveals their risk tolerance far better than a questionnaire answer does. Revealed tolerance can
only lower the client's risk class, never raise it, so behaviour always makes advice safer.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from .allocation import Allocation
from .profiling import InvestorProfile

DATA = Path(__file__).parent / "data" / "rehearsal_2008.json"

# Portfolio drawdown at the moment of selling → the highest class that behaviour supports.
# Thresholds follow the typical worst-year losses of C1–C4 model portfolios.
REVEALED_THRESHOLDS = ((0.05, 1), (0.10, 2), (0.15, 3), (0.25, 4))

Action = Literal["sell", "hold", "buy_more"]


@lru_cache(maxsize=1)
def load_scenario() -> dict[str, Any]:
    return json.loads(DATA.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class PathPoint:
    month: str
    value: float
    drawdown: float  # from the running peak, as a positive fraction
    headline: str | None


def portfolio_path(allocation: Allocation, scenario: dict[str, Any] | None = None) -> list[PathPoint]:
    """Buy-and-hold value of the allocation's asset-class mix through the scenario, month by month."""

    scenario = scenario or load_scenario()
    sleeves = {asset: allocation.amount * weight for asset, weight in allocation.strategic_weights.items() if weight > 0}
    points = [PathPoint(scenario["base_month"], allocation.amount, 0.0, None)]
    peak = allocation.amount
    for row in scenario["months"]:
        for asset in sleeves:
            sleeves[asset] *= 1 + row["returns"][asset]
        value = sum(sleeves.values())
        peak = max(peak, value)
        points.append(PathPoint(row["month"], value, 1 - value / peak, row.get("headline")))
    return points


def revealed_class(drawdown_at_sale: float) -> int:
    for ceiling, investor_class in REVEALED_THRESHOLDS:
        if drawdown_at_sale < ceiling:
            return investor_class
    return 5


@dataclass(frozen=True)
class RehearsalOutcome:
    action: Action
    month_index: int
    month: str
    drawdown_at_decision: float
    value_at_decision: float
    final_value_if_held: float
    final_value_of_choice: float
    max_drawdown: float
    trough_month: str
    revealed_class: int | None
    stated_tolerance_class: int
    previous_class: int
    new_class: int
    stated_max_loss: float | None
    reason_code: str

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def evaluate(
    allocation: Allocation,
    profile: InvestorProfile,
    action: Action,
    month_index: int,
    stated_max_loss: float | None = None,
    scenario: dict[str, Any] | None = None,
) -> RehearsalOutcome:
    """Score the client's decision. Selling moves the whole portfolio to cash from that month on."""

    scenario = scenario or load_scenario()
    path = portfolio_path(allocation, scenario)
    if not 0 <= month_index < len(path):
        raise ValueError("month_index outside the rehearsal window")
    trough = max(path, key=lambda p: p.drawdown)
    final_held = path[-1].value
    point = path[month_index]
    if action == "sell":
        value = point.value
        for row in scenario["months"][month_index:]:  # path[i] is after month i-1, so cash earns from month i
            value *= 1 + row["returns"]["cash"]
        final_choice = value
        revealed: int | None = revealed_class(point.drawdown)
    else:
        final_choice = final_held
        revealed = None  # holding or buying more never raises the class
    new_class = min(profile.investor_class, revealed) if revealed else profile.investor_class
    code = f"REVEALED_TOLERANCE_C{revealed}" if revealed and revealed < profile.investor_class else ("REHEARSAL_HELD" if action != "sell" else "REHEARSAL_SOLD_WITHIN_CLASS")
    return RehearsalOutcome(
        action=action,
        month_index=month_index,
        month=point.month,
        drawdown_at_decision=point.drawdown,
        value_at_decision=point.value,
        final_value_if_held=final_held,
        final_value_of_choice=final_choice,
        max_drawdown=trough.drawdown,
        trough_month=trough.month,
        revealed_class=revealed,
        stated_tolerance_class=profile.tolerance_class,
        previous_class=profile.investor_class,
        new_class=new_class,
        stated_max_loss=stated_max_loss,
        reason_code=code,
    )


def apply_outcome(profile: InvestorProfile, outcome: RehearsalOutcome) -> InvestorProfile:
    """Return the profile with revealed tolerance applied. Classes only ever go down."""

    if outcome.new_class >= profile.investor_class:
        return dataclasses.replace(profile, reason_codes=(*profile.reason_codes, outcome.reason_code))
    return dataclasses.replace(
        profile,
        investor_class=outcome.new_class,
        tolerance_class=min(profile.tolerance_class, outcome.new_class),
        reason_codes=(*profile.reason_codes, outcome.reason_code),
    )
