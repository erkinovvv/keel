"""Write the real-data C1–C5 backtest report."""

from __future__ import annotations

import json
from pathlib import Path

from wealth_advisor.market import backtest_model_portfolios, load_market_data


def main() -> None:
    data = load_market_data()
    output = Path(__file__).parents[1] / "data" / "market" / "backtest.json"
    report = {
        "data_window": [data.months[0], data.months[-1]],
        "method": "Static monthly-rebalanced C1-C5 strategic weights; realised volatility is monthly standard deviation annualised by sqrt(12); drawdown is peak-to-trough wealth loss.",
        "portfolios": backtest_model_portfolios(data),
    }
    output.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
