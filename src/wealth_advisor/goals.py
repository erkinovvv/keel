"""Goal planning: Monte Carlo projection of a portfolio towards a savings target.

The simulation is deterministic (fixed seed) so the same inputs always give the same answer,
which keeps advice reproducible and auditable.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

DEFAULT_PATHS = 5_000
DEFAULT_SEED = 20261020
TARGET_CONFIDENCE = 0.80


@dataclass(frozen=True)
class GoalInput:
    target: float
    years: int
    initial: float
    monthly: float = 0.0
    expected_return: float = 0.05  # annual, arithmetic, net of fees
    volatility: float = 0.10  # annual
    inflation: float = 0.0  # annual; when > 0 the target is in today's money

    def validate(self) -> None:
        if self.target <= 0 or self.initial < 0 or self.monthly < 0:
            raise ValueError("target must be positive; initial and monthly cannot be negative")
        if not 1 <= self.years <= 50:
            raise ValueError("years must be between 1 and 50")
        if not -0.5 < self.expected_return < 0.5 or not 0 <= self.volatility < 1:
            raise ValueError("expected_return or volatility out of range")
        if not 0 <= self.inflation < 0.2:
            raise ValueError("inflation out of range")


@dataclass(frozen=True)
class GoalResult:
    probability: float
    target_nominal: float
    contributions: float
    terminal_p10: float
    terminal_p50: float
    terminal_p90: float
    median_shortfall: float
    required_monthly: float | None
    fan: list[dict[str, float]]
    assumptions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["assumptions"] = list(self.assumptions)
        return result


def _simulate(goal: GoalInput, monthly: float, paths: int, seed: int) -> np.ndarray:
    """Return portfolio values at each year end, shape (paths, years + 1)."""

    months = goal.years * 12
    sigma_m = goal.volatility / math.sqrt(12)
    # Log-normal monthly growth whose expectation compounds to (1 + expected_return) per year.
    mu_m = math.log1p(goal.expected_return) / 12 - 0.5 * sigma_m**2
    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal((paths, months))
    growth = np.exp(mu_m + sigma_m * shocks)
    values = np.empty((paths, goal.years + 1))
    wealth = np.full(paths, goal.initial, dtype=float)
    values[:, 0] = wealth
    for month in range(months):
        wealth = wealth * growth[:, month] + monthly
        if (month + 1) % 12 == 0:
            values[:, (month + 1) // 12] = wealth
    return values


def _probability(goal: GoalInput, monthly: float, target: float, paths: int, seed: int) -> float:
    return float(np.mean(_simulate(goal, monthly, paths, seed)[:, -1] >= target))


def required_monthly(goal: GoalInput, target_nominal: float, confidence: float = TARGET_CONFIDENCE, paths: int = DEFAULT_PATHS, seed: int = DEFAULT_SEED) -> float | None:
    """Smallest monthly saving (to the nearest 10) that reaches the target with the given confidence."""

    if _probability(goal, 0.0, target_nominal, paths, seed) >= confidence:
        return 0.0
    high = max(100.0, target_nominal / (goal.years * 12))
    for _ in range(20):  # common random numbers make probability monotone in the contribution
        if _probability(goal, high, target_nominal, paths, seed) >= confidence:
            break
        high *= 2
    else:
        return None
    low = 0.0
    while high - low > 10:
        mid = (low + high) / 2
        if _probability(goal, mid, target_nominal, paths, seed) >= confidence:
            high = mid
        else:
            low = mid
    return math.ceil(high / 10) * 10


def project_goal(goal: GoalInput, paths: int = DEFAULT_PATHS, seed: int = DEFAULT_SEED) -> GoalResult:
    """Simulate the goal and explain the result with percentiles and a required-saving figure."""

    goal.validate()
    target_nominal = goal.target * (1 + goal.inflation) ** goal.years
    values = _simulate(goal, goal.monthly, paths, seed)
    terminal = values[:, -1]
    p10, p25, p50, p75, p90 = np.percentile(values, [10, 25, 50, 75, 90], axis=0)
    fan = [
        {"year": year, "p10": float(p10[year]), "p25": float(p25[year]), "p50": float(p50[year]), "p75": float(p75[year]), "p90": float(p90[year])}
        for year in range(goal.years + 1)
    ]
    assumptions = (
        f"{paths:,} simulated paths, monthly steps, fixed seed {seed} (reproducible)",
        f"Expected return {goal.expected_return:.2%} a year after fees, volatility {goal.volatility:.2%}",
        "Returns are log-normal and independent month to month; real markets have fatter tails",
        "Contributions are added at the end of each month; no taxes",
        f"Target grows with {goal.inflation:.1%} inflation" if goal.inflation else "Target is in nominal money",
    )
    return GoalResult(
        probability=float(np.mean(terminal >= target_nominal)),
        target_nominal=target_nominal,
        contributions=goal.initial + goal.monthly * goal.years * 12,
        terminal_p10=float(np.percentile(terminal, 10)),
        terminal_p50=float(np.percentile(terminal, 50)),
        terminal_p90=float(np.percentile(terminal, 90)),
        median_shortfall=float(max(0.0, target_nominal - np.percentile(terminal, 50))),
        required_monthly=required_monthly(goal, target_nominal, paths=paths, seed=seed),
        fan=fan,
        assumptions=assumptions,
    )
