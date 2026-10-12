"""Read-only, allowlisted public market quotes. Prices are observations, not forecasts."""

from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .catalog import DATA_DIR, Product, load_catalog


ALLOWED_HOSTS = frozenset({"hq.sinajs.cn", "qt.gtimg.cn", "query1.finance.yahoo.com", "api.fund.eastmoney.com"})
TIMEOUT_SECONDS = 3
CACHE_SECONDS = 60
SNAPSHOT_DATE = "2026-10-12"
_SNAPSHOT_PRICES = {
    "csi300": (4287.9798, -0.68),
    "sse": (3797.2424, -0.43),
    "hsi": (24271.2, 0.25),
    "sp500": (7815.96, 0.057),
    "nasdaq100": (30763.615, -0.387),
    "gold": (4197.0, -0.458),
    "usd_cny": (6.6932, 0.0179),
    "cn10y": (1.714, None),
}
_INDICES = {
    "csi300": ("CSI 300", "沪深300", (("sina", "s_sh000300"), ("tencent", "s_sh000300"))),
    "sse": ("SSE Composite", "上证指数", (("sina", "s_sh000001"), ("tencent", "s_sh000001"))),
    "hsi": ("Hang Seng", "恒生指数", (("tencent", "s_hkHSI"), ("yahoo", "^HSI"))),
    "sp500": ("S&P 500", "标普500", (("yahoo", "^GSPC"), ("tencent", "usINX"))),
    "nasdaq100": ("Nasdaq-100", "纳斯达克100", (("yahoo", "^NDX"), ("tencent", "usNDX"))),
    "gold": ("Gold futures (USD/oz)", "纽约黄金期货（美元/盎司）", (("sina", "hf_GC"), ("yahoo", "GC=F"))),
    "usd_cny": ("USD/CNY", "美元兑人民币", (("sina", "fx_susdcny"), ("yahoo", "CNY=X"))),
    "cn10y": ("China 10-year government yield", "中国十年期国债收益率", (("sina", "globalbd_cn10yt"),)),
}
_PROVIDER_LINE = re.compile(r'(?:var hq_str_|v_)([A-Za-z0-9_]+)="([^"]*)"')
_FUND_CODE = re.compile(r"CN-(\d{6})\Z")


@dataclass(frozen=True)
class MarketQuote:
    id: str
    name_en: str
    name_zh: str
    price: float
    change_pct: float | None
    as_of: str
    source: str
    stale: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request: Request, fp: Any, code: int, message: str, headers: Any, newurl: str) -> None:
        raise ValueError("market provider redirect rejected")


def _default_fetch(url: str, headers: dict[str, str], timeout: float) -> bytes:
    request = Request(url, headers=headers)
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        return response.read(1_000_001)


def _validated_numbers(price: Any, change_pct: Any) -> tuple[float, float | None]:
    price = float(price)
    change = None if change_pct in (None, "") else float(change_pct)
    if not math.isfinite(price) or not 0 < price < 10_000_000:
        raise ValueError("market price outside sanity bounds")
    if change is not None and (not math.isfinite(change) or abs(change) > 30):
        raise ValueError("market move outside sanity bounds")
    return price, change


def _provider_fields(payload: str, symbol: str) -> list[str]:
    for match in _PROVIDER_LINE.finditer(payload):
        if match.group(1) == symbol:
            return match.group(2).split("~" if payload[match.start():].startswith("v_") else ",")
    raise ValueError("missing market symbol")


def _parse_index(provider: str, symbol: str, payload: bytes) -> tuple[float, float | None, str]:
    if provider == "yahoo":
        result = json.loads(payload)["chart"]["result"][0]
        meta = result["meta"]
        if meta["symbol"] != symbol:
            raise ValueError("unexpected Yahoo symbol")
        price, change = _validated_numbers(meta["regularMarketPrice"], meta.get("regularMarketChangePercent"))
        as_of = datetime.fromtimestamp(int(meta["regularMarketTime"]), timezone.utc).isoformat()
        return price, change, as_of
    try:
        text = payload.decode("gbk")
    except UnicodeDecodeError:
        text = payload.decode("utf-8")
    values = _provider_fields(text, symbol)
    if provider == "sina":
        if symbol == "globalbd_cn10yt":
            price, _ = _validated_numbers(values[1], None)
            return price, None, f"{values[12]}T{values[13]}"
        if symbol.startswith("s_"):
            price, change = _validated_numbers(values[1], values[3])
            as_of = datetime.now(timezone.utc).isoformat()
        elif symbol == "hf_GC":
            price, _ = _validated_numbers(values[0], None)
            previous, _ = _validated_numbers(values[7], None)
            _, change = _validated_numbers(price, (price / previous - 1) * 100)
            as_of = f"{values[12]}T{values[6]}"
        else:
            price, change = _validated_numbers(values[1], values[10])
            as_of = f"{values[17]}T{values[0]}"
        return price, change, as_of
    price, change = _validated_numbers(values[3], values[32] if symbol.startswith("us") else values[5])
    as_of = values[30].replace(" ", "T") if symbol.startswith("us") else datetime.now(timezone.utc).isoformat()
    return price, change, as_of


def _parse_fund(provider: str, code: str, payload: bytes) -> tuple[float, float | None, str]:
    if provider == "eastmoney":
        body = json.loads(payload)
        if body.get("ErrCode") != 0:
            raise ValueError("East Money rejected fund lookup")
        rows = body["Data"]["LSJZList"]
        latest = rows[0]
        change = latest.get("JZZZL")
        if change in (None, "") and len(rows) > 1:
            previous = float(rows[1]["DWJZ"])
            change = (float(latest["DWJZ"]) / previous - 1) * 100 if previous > 0 else None
        price, change = _validated_numbers(latest["DWJZ"], change)
        return price, change, latest["FSRQ"]
    try:
        text = payload.decode("gbk")
    except UnicodeDecodeError:
        text = payload.decode("utf-8")
    values = _provider_fields(text, f"jj{code}")
    if values[0] != code:
        raise ValueError("unexpected Tencent fund")
    price, change = _validated_numbers(values[5], values[7])
    return price, change, values[8]


def _request_spec(provider: str, symbol: str) -> tuple[str, dict[str, str]]:
    if provider == "sina":
        return f"https://hq.sinajs.cn/list={symbol}", {"Referer": "https://finance.sina.com.cn/"}
    if provider == "tencent":
        return f"https://qt.gtimg.cn/q={symbol}", {}
    if provider == "yahoo":
        return f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?range=5d&interval=1d", {}
    return f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={symbol}&pageIndex=1&pageSize=2", {"Referer": "https://fundf10.eastmoney.com/"}


class LiveMarket:
    """Refresh fixed symbols only; no provider payload crosses this boundary."""

    def __init__(self, fetcher: Callable[[str, dict[str, str], float], bytes] | None = None, *, enabled: bool | None = None, clock: Callable[[], float] = time.monotonic):
        self.fetcher = fetcher or _default_fetch
        self.enabled = enabled
        self.clock = clock
        self._cache: dict[str, tuple[float, MarketQuote]] = {}
        self._funds = {product.id: product for product in load_catalog(DATA_DIR / "products_cn.json") if _FUND_CODE.fullmatch(product.id)}
        meta_path = DATA_DIR / "products_cn_meta.json"
        self._meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"as_of": SNAPSHOT_DATE, "funds": {}}

    def _network_enabled(self) -> bool:
        return self.enabled if self.enabled is not None else os.getenv("LIVE_MARKET", "1") == "1"

    def _fetch(self, provider: str, symbol: str) -> bytes:
        url, headers = _request_spec(provider, symbol)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError("market host not allowlisted")
        payload = self.fetcher(url, {"User-Agent": "Mozilla/5.0 Keel/1.0", **headers}, TIMEOUT_SECONDS)
        if len(payload) > 1_000_000:
            raise ValueError("market payload too large")
        return payload

    def _quote(self, key: str, audit: Any = None) -> MarketQuote:
        cached = self._cache.get(key)
        if cached and self.clock() - cached[0] < CACHE_SECONDS:
            return cached[1]
        if key in _INDICES:
            name_en, name_zh, providers = _INDICES[key]
            snapshot_price, snapshot_change = _SNAPSHOT_PRICES[key]
            snapshot = MarketQuote(key, name_en, name_zh, snapshot_price, snapshot_change, SNAPSHOT_DATE, "dated_snapshot", True)
        else:
            product = self._funds[key]
            meta = self._meta["funds"][key]
            name_en, name_zh = meta["name_en"], meta["name_zh"]
            snapshot = MarketQuote(key, name_en, name_zh, product.nav, None, self._meta["as_of"], "catalog_snapshot", True)
            providers = (("eastmoney", meta["code"]), ("tencent", f"jj{meta['code']}"))
        result = snapshot
        if self._network_enabled():
            for provider, symbol in providers:
                try:
                    payload = self._fetch(provider, symbol)
                    price, change, as_of = _parse_index(provider, symbol, payload) if key in _INDICES else _parse_fund(provider, symbol.removeprefix("jj"), payload)
                    result = MarketQuote(key, name_en, name_zh, price, change, as_of, provider)
                    break
                except (ValueError, TypeError, KeyError, IndexError, UnicodeError, OSError, TimeoutError):
                    continue
        self._cache[key] = (self.clock(), result)
        if audit is not None:
            audit.append("market_refresh", {"id": key, "source": result.source, "as_of": result.as_of, "stale": result.stale})
        return result

    def indices(self, audit: Any = None) -> list[MarketQuote]:
        return [self._quote(key, audit) for key in _INDICES]

    def funds(self, ids: list[str] | None = None, audit: Any = None) -> list[MarketQuote]:
        selected = ids if ids is not None else list(self._funds)
        selected = [key for key in selected if key in self._funds]
        requested = set(ids or ())
        unknown = requested - set(self._funds) - {key for key in requested if key.startswith(("dep-", "lcd-", "sb-"))}
        if unknown:
            raise ValueError("fund is not in the CN catalog allowlist")
        return [self._quote(key, audit) for key in dict.fromkeys(selected)]
