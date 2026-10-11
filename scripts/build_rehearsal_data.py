"""Build the Crash Rehearsal dataset: real monthly asset-class returns, Oct 2007 – Mar 2013.

    uv run python scripts/build_rehearsal_data.py

Sources (downloaded at build time, cited in the output):
- Equity, cash: Kenneth R. French Data Library, Fama/French 3 Factors (monthly Mkt-RF + RF, RF).
- Real estate: Kenneth R. French Data Library, 49 Industry Portfolios, value-weighted "RlEst".
- Bonds: FRED GS10 (10-year US Treasury constant-maturity yield), converted to a monthly total
  return with a duration approximation: r_t = y_{t-1}/12 - D * (y_t - y_{t-1}), D = 6.
- Gold: World Bank Commodity Price Data (Pink Sheet) via datasets/gold-prices (ODC-PDDL).
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
import zipfile
from pathlib import Path

OUT = Path(__file__).parents[1] / "src" / "wealth_advisor" / "data" / "rehearsal_2008.json"
FRENCH = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
START, END = "2007-09", "2013-03"  # September is the base month; returns start in October 2007
DURATION = 6.0

HEADLINES = {
    "2007-10": "US stocks close at an all-time high",
    "2008-01": "Fed cuts rates in an emergency move as markets slide",
    "2008-03": "Bear Stearns rescued in a deal with JPMorgan",
    "2008-07": "IndyMac Bank fails; mortgage lenders under pressure",
    "2008-09": "Lehman Brothers files for bankruptcy; AIG rescued",
    "2008-10": "Congress passes $700bn bank rescue; stocks suffer their worst week in decades",
    "2008-11": "Citigroup receives a government rescue",
    "2008-12": "Fed cuts rates to near zero",
    "2009-01": "Job losses mount as the recession deepens",
    "2009-02": "Stimulus package signed into law; stocks keep falling",
    "2009-03": "Stocks hit a 12-year low",
    "2009-04": "Markets rally as bank stress tests approach",
    "2009-12": "A year after the panic, stocks are up sharply from the low",
    "2010-05": "Euro-area debt crisis shakes markets",
    "2011-08": "US credit rating downgraded; markets swing",
    "2012-09": "Central banks launch new support programmes",
    "2013-03": "US stocks return to their 2007 peak",
}


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research data build)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _french_section(zip_name: str, first_column_header_contains: str | None = None) -> dict[str, dict[str, float]]:
    """Parse the first monthly table of a French library CSV into {YYYY-MM: {column: percent}}."""

    archive = zipfile.ZipFile(io.BytesIO(_get(FRENCH + zip_name)))
    text = archive.read(archive.namelist()[0]).decode("latin-1")
    rows: dict[str, dict[str, float]] = {}
    header: list[str] | None = None
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if header is None:
            if len(cells) > 2 and cells[0] == "" and (first_column_header_contains is None or first_column_header_contains in cells):
                header = cells
            continue
        if not cells[0].isdigit() or len(cells[0]) != 6:
            if rows:
                break  # end of the first (monthly, value-weighted) section
            continue
        month = f"{cells[0][:4]}-{cells[0][4:]}"
        rows[month] = {name: float(value) for name, value in zip(header[1:], cells[1:]) if name}
    return rows


def main() -> None:
    factors = _french_section("F-F_Research_Data_Factors_CSV.zip", "Mkt-RF")
    industries = _french_section("49_Industry_Portfolios_CSV.zip", "RlEst")
    gs10 = {row["observation_date"][:7]: float(row["GS10"]) for row in csv.DictReader(io.StringIO(_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=GS10").decode()))}
    gold = {row["Date"][:7]: float(row["Price"]) for row in csv.DictReader(io.StringIO(_get("https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv").decode()))}

    months = sorted(m for m in factors if START < m <= END)
    previous = {m: p for m, p in zip(months, [START, *months[:-1]])}
    rows = []
    for month in months:
        prior = previous[month]
        f = factors[month]
        returns = {
            "equity": (f["Mkt-RF"] + f["RF"]) / 100,
            "bonds": gs10[prior] / 1200 - DURATION * (gs10[month] - gs10[prior]) / 100,
            "cash": f["RF"] / 100,
            "gold": gold[month] / gold[prior] - 1,
            "reits": industries[month]["RlEst"] / 100,
        }
        rows.append({"month": month, "returns": {k: round(v, 6) for k, v in returns.items()}, "headline": HEADLINES.get(month)})

    OUT.write_text(json.dumps({
        "name": "2008 global financial crisis and recovery",
        "base_month": START,
        "window": [months[0], months[-1]],
        "method": "Monthly total returns per asset class. Bonds approximated from 10-year Treasury yield changes with duration 6. US data as a proxy for global markets.",
        "sources": [
            {"asset": "equity, cash", "source": "Kenneth R. French Data Library, Fama/French 3 Factors (monthly)", "url": FRENCH},
            {"asset": "reits", "source": "Kenneth R. French Data Library, 49 Industry Portfolios, value-weighted RlEst", "url": FRENCH},
            {"asset": "bonds", "source": "FRED GS10, Board of Governors of the Federal Reserve System", "url": "https://fred.stlouisfed.org/series/GS10"},
            {"asset": "gold", "source": "World Bank Commodity Price Data (Pink Sheet) via datasets/gold-prices, ODC-PDDL", "url": "https://github.com/datasets/gold-prices"},
        ],
        "months": rows,
    }, indent=1), encoding="utf-8")
    print(f"wrote {len(rows)} months to {OUT}")


if __name__ == "__main__":
    main()
