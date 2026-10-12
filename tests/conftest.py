import pytest


@pytest.fixture(autouse=True)
def disable_live_market(monkeypatch):
    """Keep the test suite deterministic while the application defaults to live quotes."""

    monkeypatch.setenv("LIVE_MARKET", "0")
