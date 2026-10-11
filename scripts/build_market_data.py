"""Download and process free monthly market data for M7.

Run with::

    uv run python scripts/build_market_data.py

The output is intentionally a small, reviewable JSON file rather than a runtime
network dependency. See ``data/market/SOURCES.md`` for provenance and use notes.
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

from build_rehearsal_data import FRENCH, _french_section, _get
from wealth_advisor.market import MarketData, estimate_market_parameters


OUT = Path(__file__).parents[1] / "data" / "market" / "returns.json"
ESTIMATE_OUT = OUT.with_name("estimates.json")
START = "2008-01"


def _fred_series() -> dict[str, float]:
    rows = csv.DictReader(io.StringIO(_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=GS10").decode()))
    return {row["observation_date"][:7]: float(row["GS10"]) for row in rows if row["GS10"] not in ("", ".")}


def _gold_series() -> dict[str, float]:
    rows = csv.DictReader(io.StringIO(_get("https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv").decode()))
    return {row["Date"][:7]: float(row["Price"]) for row in rows if row["Price"] not in ("", ".")}


def main() -> None:
    factors = _french_section("F-F_Research_Data_Factors_CSV.zip", "Mkt-RF")
    industries = _french_section("49_Industry_Portfolios_CSV.zip", "RlEst")
    gs10 = _fred_series()
    gold = _gold_series()
    common = sorted(set(factors) & set(industries) & set(gs10) & set(gold))
    months = [month for month in common if month >= START]
    previous = {month: common[common.index(month) - 1] for month in months}
    rows: list[dict[str, object]] = []
    for month in months:
        prior = previous[month]
        factor = factors[month]
        values = {
            "equity": (factor["Mkt-RF"] + factor["RF"]) / 100,
            "bonds": gs10[prior] / 1200 - 6.0 * (gs10[month] - gs10[prior]) / 100,
            "cash": factor["RF"] / 100,
            "gold": gold[month] / gold[prior] - 1,
            "reits": industries[month]["RlEst"] / 100,
        }
        if all(math.isfinite(value) for value in values.values()):
            rows.append({"month": month, **{asset: round(value, 8) for asset, value in values.items()}})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asset_classes": ["equity", "bonds", "cash", "gold", "reits"],
        "frequency": "monthly",
        "start": rows[0]["month"],
        "end": rows[-1]["month"],
        "method": "Equity and cash are Fama/French Mkt-RF plus RF and RF. Bonds use GS10 yield changes with duration 6. Gold is the World Bank monthly price return. REITs use the value-weighted RlEst industry portfolio.",
        "returns": rows,
        "sources": [
            {"name": "Kenneth R. French Data Library", "url": FRENCH},
            {"name": "FRED GS10", "url": "https://fred.stlouisfed.org/series/GS10"},
            {"name": "World Bank Pink Sheet via datasets/gold-prices", "url": "https://github.com/datasets/gold-prices"},
        ],
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    estimate = estimate_market_parameters(MarketData.from_dict(payload))
    ESTIMATE_OUT.write_text(json.dumps({
        "observations": estimate.observations,
        "annual_expected_returns": estimate.annual_expected_returns,
        "annual_covariance": estimate.annual_covariance,
        "ledoit_wolf_shrinkage": estimate.shrinkage,
    }, indent=1), encoding="utf-8")
    print(f"wrote {len(rows)} monthly observations to {OUT}")


if __name__ == "__main__":
    main()
