"""Build a product catalog of real Chinese public mutual funds (公募基金) from open data.

    uv run python scripts/build_cn_catalog.py

Source: East Money / Tiantian Fund public pages (the same open source the AkShare library uses):
  - fund.eastmoney.com/pingzhongdata/<code>.js  daily accumulated NAV, 7-day money-market yield, minimum purchase
  - fund.eastmoney.com/<code>.html               distributor risk level (低风险 … 高风险 → R1 … R5)
  - fundf10.eastmoney.com/jjfl_<code>.html       management, custody and sales-service fees

Writes src/wealth_advisor/data/products_cn.json (engine schema) and products_cn_meta.json
(codes, Chinese names, history statistics, sources, as-of date). Expected returns are shrunk
halfway towards an asset-class prior, because a single fund's past return is a poor forecast.
"""

from __future__ import annotations

import json
import math
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parents[1] / "src" / "wealth_advisor" / "data"

# code, English name, asset class, region, liquidity days (redemption to cash)
FUNDS = [
    ("000198", "Tianhong Yu'E Bao Money Market", "cash", "CN", 1),
    ("000009", "E Fund Daily Money Market A", "cash", "CN", 1),
    ("001821", "Aegon-Industrial Tiantianyi Money Market B", "cash", "CN", 1),
    ("217022", "China Merchants Industry Bond A", "bonds", "CN", 3),
    ("070009", "Harvest Ultra-Short Bond C", "bonds", "CN", 2),
    ("100018", "Fullgoal Tianli Growth Bond A", "bonds", "CN", 3),
    ("050027", "Bosera Credit Pure Bond A", "bonds", "CN", 3),
    ("161119", "E Fund China Bond New Composite Index A", "bonds", "CN", 3),
    ("003376", "GF CDB 7-10Y Policy Bank Bond Index A", "bonds", "CN", 3),
    ("110007", "E Fund Steady Income Bond A", "bonds", "CN", 3),
    ("110027", "E Fund Anxin Return Bond A", "bonds", "CN", 3),
    ("000171", "E Fund Yufeng Return Bond A", "bonds", "CN", 3),
    ("270002", "GF Steady Growth Hybrid A", "bonds", "CN", 3),
    ("001316", "Essence Steady Value-Add Hybrid A", "bonds", "CN", 3),
    ("000215", "GF Trend Select Flexible Allocation Hybrid A", "bonds", "CN", 3),
    ("110020", "E Fund CSI 300 ETF Feeder A", "equity", "CN", 3),
    ("160119", "Southern CSI 500 ETF Feeder A", "equity", "CN", 3),
    ("007466", "Huatai-PineBridge CSI Dividend Low Volatility ETF Feeder A", "equity", "CN", 3),
    ("000071", "ChinaAMC Hang Seng ETF Feeder A", "equity", "HK", 4),
    ("050025", "Bosera S&P 500 ETF Feeder A", "equity", "US", 10),
    ("270042", "GF Nasdaq-100 ETF Feeder A (QDII)", "equity", "US", 10),
    ("005827", "E Fund Blue Chip Select Hybrid", "equity", "CN", 3),
    ("000216", "Hua An Gold ETF Feeder A", "gold", "CN", 3),
    ("000179", "GF US Real Estate Index A (QDII)", "reits", "US", 10),
]
# Long-run annual return assumptions in CNY terms used as the shrinkage prior.
PRIOR = {"cash": 0.015, "bonds": 0.03, "equity": 0.07, "gold": 0.045, "reits": 0.06}
RISK_TEXT = {"低风险": 1, "中低风险": 2, "中风险": 3, "中高风险": 4, "高风险": 5}
YEARS = 10


def _get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research catalog build)", "Referer": "https://fund.eastmoney.com/"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8-sig", errors="replace")


def _js_var(text: str, name: str):
    match = re.search(rf"var {name}\s*=\s*(.*?);\s*(?:/\*|var |$)", text, re.S)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip('"')


def _month_ends(points: list[list[float]]) -> list[tuple[str, float]]:
    by_month: dict[str, float] = {}
    for ms, value in points:
        if value is None:
            continue
        month = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m")
        by_month[month] = float(value)
    return sorted(by_month.items())


def _stats(series: list[tuple[str, float]]) -> dict[str, float]:
    series = series[-(YEARS * 12 + 1):]
    values = [v for _, v in series]
    returns = [b / a - 1 for a, b in zip(values, values[1:]) if a > 0]
    years = len(returns) / 12
    cagr = (values[-1] / values[0]) ** (1 / years) - 1
    mean = sum(math.log1p(r) for r in returns) / len(returns)
    vol = math.sqrt(sum((math.log1p(r) - mean) ** 2 for r in returns) / (len(returns) - 1) * 12)
    peak, max_dd = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        max_dd = max(max_dd, 1 - v / peak)
    return {"from": series[0][0], "to": series[-1][0], "years": round(years, 1), "cagr": cagr, "volatility": vol, "max_drawdown": max_dd}


def _fees(code: str) -> dict[str, float]:
    html = re.sub(r"<[^>]+>", " ", _get(f"https://fundf10.eastmoney.com/jjfl_{code}.html"))
    fees = {}
    for label, key in (("管理费率", "management"), ("托管费率", "custody"), ("销售服务费率", "sales_service")):
        match = re.search(rf"{label}\s*([\d.]+)%", html)
        fees[key] = float(match.group(1)) / 100 if match else 0.0
    return fees


def _risk(code: str) -> tuple[int, str]:
    html = _get(f"https://fund.eastmoney.com/{code}.html")
    for text in ("中低风险", "中高风险", "低风险", "中风险", "高风险"):  # longest first
        if text in html:
            return RISK_TEXT[text], text
    raise ValueError("risk level not found")


def build_one(code: str, name_en: str, asset_class: str, region: str, liquidity_days: int) -> tuple[dict, dict]:
    js = _get(f"https://fund.eastmoney.com/pingzhongdata/{code}.js")
    name_zh = _js_var(js, "fS_name")
    min_purchase = float(_js_var(js, "fund_minsg") or 10)
    try:
        risk_class, risk_text = _risk(code)
    except ValueError:
        if asset_class != "cash":
            raise
        risk_class, risk_text = 1, "低风险"  # money market funds are low risk by regulation (CSRC MMF rules)
    fees = _fees(code)
    ongoing_fee = round(sum(fees.values()), 5)
    if asset_class == "cash":
        yields = [p[1] for p in (_js_var(js, "Data_sevenDaysYearIncome") or []) if p[1] is not None]
        recent = yields[-250:]
        history = {"seven_day_yield_latest": yields[-1] / 100, "seven_day_yield_1y_avg": sum(recent) / len(recent) / 100}
        expected = history["seven_day_yield_1y_avg"] + ongoing_fee  # quoted yields are after fees; the engine nets fees
        volatility = 0.002
        nav = 1.0
    else:
        history = _stats(_month_ends(_js_var(js, "Data_ACWorthTrend")))
        expected = 0.5 * (history["cagr"] + ongoing_fee) + 0.5 * PRIOR[asset_class]  # gross of fees; the engine nets fees
        volatility = history["volatility"]
        nav = float(_js_var(js, "Data_netWorthTrend")[-1]["y"])
    product = {
        "id": f"CN-{code}",
        "name": f"{name_en} ({code})",
        "asset_class": asset_class,
        "region": region,
        "risk_class": risk_class,
        "expected_return": round(expected, 5),
        "volatility": round(volatility, 5),
        "fee": ongoing_fee,
        "liquidity_days": liquidity_days,
        "min_investment": max(min_purchase, 1.0),
        "nav": round(nav, 4),
    }
    meta = {
        "code": code,
        "name_zh": name_zh,
        "name_en": name_en,
        "risk_text": risk_text,
        "fees": fees,
        "history": {k: (round(v, 5) if isinstance(v, float) else v) for k, v in history.items()},
        "source": f"https://fund.eastmoney.com/{code}.html",
    }
    return product, meta


def main() -> None:
    products, metas = [], {}
    for fund in FUNDS:
        try:
            product, meta = build_one(*fund)
        except Exception as exc:  # one bad page must not lose the whole catalog
            print(f"skip {fund[0]}: {type(exc).__name__}: {exc}")
            continue
        products.append(product)
        metas[product["id"]] = meta
        print(f"{product['id']}  R{product['risk_class']}  ret {product['expected_return']:.2%}  vol {product['volatility']:.2%}  fee {product['fee']:.2%}  {meta['name_zh']}")
    (DATA / "products_cn.json").write_text(json.dumps(products, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "products_cn_meta.json").write_text(json.dumps({
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "currency": "CNY",
        "source": "East Money / Tiantian Fund public fund pages (as used by the open-source AkShare library)",
        "method": f"Volatility from {YEARS}-year monthly accumulated-NAV returns; expected return = 50% historical CAGR (gross of ongoing fees) + 50% asset-class prior; money funds use the 1-year average 7-day yield.",
        "funds": metas,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(products)} funds")


if __name__ == "__main__":
    main()
