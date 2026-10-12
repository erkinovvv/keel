import json
from pathlib import Path

import pytest

from wealth_advisor.live_market import LiveMarket, _parse_fund, _parse_index


FIXTURES = Path(__file__).parent / "fixtures" / "market"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_real_provider_samples_parse_to_typed_values():
    price, change, _ = _parse_index("sina", "s_sh000300", fixture_bytes("sina.txt"))
    assert price == pytest.approx(4287.9798) and change == pytest.approx(-0.68)
    price, change, _ = _parse_index("tencent", "usINX", fixture_bytes("tencent.txt"))
    assert price == pytest.approx(7814.93) and change == pytest.approx(0.04)
    price, change, _ = _parse_index("yahoo", "^GSPC", fixture_bytes("yahoo.json"))
    assert price == pytest.approx(7815.96) and change == pytest.approx(0.057)
    price, change, as_of = _parse_fund("eastmoney", "270042", fixture_bytes("eastmoney.json"))
    assert price == pytest.approx(8.4745) and change == pytest.approx(0.41) and as_of == "2026-10-09"
    price, change, as_of = _parse_fund("tencent", "270042", fixture_bytes("tencent.txt"))
    assert price == pytest.approx(8.4745) and change == pytest.approx(0.4088) and as_of == "2026-10-09"


def test_bounds_reject_absurd_provider_moves():
    payload = b'var hq_str_s_sh000300="CSI,4287,0,45,0,0";'
    with pytest.raises(ValueError, match="sanity"):
        _parse_index("sina", "s_sh000300", payload)


def test_fallback_order_and_sixty_second_cache():
    calls: list[str] = []
    now = [100.0]

    def fetch(url, headers, timeout):
        calls.append(url)
        if "s_sh000300" in url and "hq.sinajs" in url:
            raise OSError("primary unavailable")
        if "s_sh000300" in url:
            return fixture_bytes("tencent.txt")
        raise AssertionError(url)

    market = LiveMarket(fetch, enabled=True, clock=lambda: now[0])
    first = market._quote("csi300")
    second = market._quote("csi300")
    assert first.source == "tencent" and second == first and len(calls) == 2
    now[0] += 60
    market._quote("csi300")
    assert len(calls) == 4


def test_disabled_or_failed_network_returns_stale_dated_snapshot():
    market = LiveMarket(lambda *args: (_ for _ in ()).throw(OSError("offline")), enabled=True)
    quote = market._quote("csi300")
    assert quote.stale and quote.source == "dated_snapshot" and quote.as_of == "2026-10-12"
    assert LiveMarket(enabled=False).indices()[0].stale


def test_fund_allowlist_rejects_unknown_id():
    with pytest.raises(ValueError, match="allowlist"):
        LiveMarket(enabled=False).funds(["CN-999999"])
