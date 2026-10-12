"""Historical-style deterministic portfolio stress tests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from .allocation import Allocation


SCENARIOS: dict[str, dict[str, float]] = {
    "2008_gfc": {"cash": 0.00, "bonds": -0.08, "equity": -0.37, "gold": 0.05, "reits": -0.40},
    "2020_covid": {"cash": 0.00, "bonds": 0.02, "equity": -0.34, "gold": -0.03, "reits": -0.30},
    "2022_rate_shock": {"cash": 0.00, "bonds": -0.13, "equity": -0.18, "gold": -0.01, "reits": -0.20},
}


@dataclass(frozen=True)
class StressResult:
    scenario: str
    loss_percent: float
    loss_amount: float
    max_tolerable_loss: float
    mismatch: bool
    shocks: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def stress_test(
    allocation: Allocation,
    scenario: str = "2008_gfc",
    *,
    custom_shocks: Mapping[str, float] | None = None,
    max_tolerable_loss: float = 0.20,
    tolerance_is_amount: bool = False,
) -> StressResult:
    """Apply asset-class shocks and flag losses above the client's stated tolerance."""

    if scenario == "custom":
        shocks = {
            asset: max(-1.0, min(1.0, float(shock)))
            for asset, shock in (custom_shocks or {}).items()
        }
    else:
        try:
            shocks = SCENARIOS[scenario]
        except KeyError as exc:
            raise ValueError(f"unknown stress scenario {scenario}") from exc
    if any(asset not in shocks for asset in {holding.asset_class for holding in allocation.holdings}):
        raise ValueError("stress shocks must cover every held asset class")
    portfolio_return = sum(
        holding.weight * (0.0 if holding.product_id.startswith(("dep-", "lcd-", "sb-")) else shocks[holding.asset_class])
        for holding in allocation.holdings
    )
    loss_percent = max(0.0, -portfolio_return)
    loss_amount = allocation.amount * loss_percent
    tolerance_amount = max_tolerable_loss if tolerance_is_amount else allocation.amount * max_tolerable_loss
    return StressResult(scenario, loss_percent, loss_amount, tolerance_amount, loss_amount > tolerance_amount, dict(shocks))
