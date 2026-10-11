"""Proactive monitoring: the advisor reaches out first when markets move.

A market event is applied to the client's current portfolio; the engine reports the change in
value, drift from the target mix, whether the client's own loss limit is breached, how the fall
compares with what the client did in the Crash Rehearsal, and — only if drift exceeds the band —
a rebalancing proposal. Everything is deterministic; the client decides, and any trade still goes
through the human confirmation path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .allocation import Allocation

# Illustrative one-month market events (asset-class returns), used to rehearse the advisor's response.
EVENTS: dict[str, dict[str, Any]] = {
    "equity_selloff": {"name": "Sharp equity sell-off", "returns": {"cash": 0.002, "bonds": 0.015, "equity": -0.20, "gold": 0.04, "reits": -0.22}},
    "rate_shock": {"name": "Interest-rate shock", "returns": {"cash": 0.003, "bonds": -0.07, "equity": -0.09, "gold": -0.02, "reits": -0.12}},
    "rally": {"name": "Strong equity rally", "returns": {"cash": 0.002, "bonds": -0.005, "equity": 0.15, "gold": -0.03, "reits": 0.10}},
}
DRIFT_BAND = 0.05  # rebalance when any asset class is more than 5 percentage points off target
MIN_TRADE = 0.005  # ignore trades below 0.5% of the portfolio


@dataclass(frozen=True)
class Trade:
    asset_class: str
    side: str  # "sell" or "buy"
    amount: float


@dataclass(frozen=True)
class MarketCheck:
    event: str
    event_name: str
    value_before: float
    value_after: float
    change: float  # fraction, negative for a loss
    weights_target: dict[str, float]
    weights_now: dict[str, float]
    max_drift: float
    drift_class: str
    rebalance_needed: bool
    trades: tuple[Trade, ...]
    loss_limit: float | None
    within_limit: bool | None
    rehearsal_sold_at: float | None
    recommendation: str  # "hold" | "rebalance" | "review_risk"
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["trades"] = [asdict(t) for t in self.trades]
        return result


def check_market(
    allocation: Allocation,
    event: str,
    *,
    loss_limit: float | None = None,
    rehearsal: dict[str, Any] | None = None,
) -> MarketCheck:
    """Apply a market event to the allocation and decide what the advisor should tell the client."""

    try:
        spec = EVENTS[event]
    except KeyError as exc:
        raise ValueError(f"unknown market event {event}") from exc
    target = {k: v for k, v in allocation.strategic_weights.items() if v > 0}
    values = {k: allocation.amount * w * (1 + spec["returns"].get(k, 0.0)) for k, w in target.items()}
    value_after = sum(values.values())
    change = value_after / allocation.amount - 1
    now = {k: v / value_after for k, v in values.items()}
    drifts = {k: now[k] - target[k] for k in target}
    drift_class = max(drifts, key=lambda k: abs(drifts[k]))
    max_drift = abs(drifts[drift_class])
    rebalance = max_drift > DRIFT_BAND
    trades = tuple(
        Trade(k, "sell" if d > 0 else "buy", round(abs(d) * value_after, 2))
        for k, d in sorted(drifts.items(), key=lambda kv: -kv[1])
        if rebalance and abs(d) >= MIN_TRADE
    )
    loss = max(0.0, -change)
    within = None if loss_limit is None else loss <= loss_limit
    sold_at = rehearsal["drawdown_at_decision"] if rehearsal and rehearsal.get("action") == "sell" else None

    codes = [f"MARKET_EVENT_{event.upper()}"]
    if within is False:
        recommendation = "review_risk"
        codes.append("LOSS_LIMIT_BREACHED")
    elif rebalance:
        recommendation = "rebalance"
        codes.append("DRIFT_ABOVE_BAND")
    else:
        recommendation = "hold"
        codes.append("WITHIN_PLAN")
    if sold_at is not None and loss >= sold_at:
        codes.append("BEYOND_REHEARSAL_SELL_POINT")
    elif sold_at is not None:
        codes.append("BEFORE_REHEARSAL_SELL_POINT")
    return MarketCheck(
        event=event,
        event_name=spec["name"],
        value_before=allocation.amount,
        value_after=value_after,
        change=change,
        weights_target=target,
        weights_now=now,
        max_drift=max_drift,
        drift_class=drift_class,
        rebalance_needed=rebalance,
        trades=trades,
        loss_limit=loss_limit,
        within_limit=within,
        rehearsal_sold_at=sold_at,
        recommendation=recommendation,
        reason_codes=tuple(codes),
    )
