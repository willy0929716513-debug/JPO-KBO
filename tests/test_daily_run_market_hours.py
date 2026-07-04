"""Verifies run_daily_pipeline() skips fresh analysis for symbols whose
market is closed and carries forward their previous entry instead, while
still freshly analyzing symbols whose market is open. Every external
provider is stubbed so this test runs offline and fast.
"""
import json

import numpy as np
import pandas as pd
import pytest

import src.pipeline.daily_run as daily_run


def _synthetic_df(seed: int, n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    high = close * 1.005
    low = close * 0.995
    open_ = close
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=dates)


@pytest.fixture(autouse=True)
def _stub_external_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_run, "DOCS_DATA_DIR", tmp_path)
    monkeypatch.setattr(daily_run, "WATCHLIST", {"equity": ["OPEN_SYM"], "taiwan": ["CLOSED_SYM"]})
    monkeypatch.setattr(daily_run, "PAIR_WATCHLIST", [])

    monkeypatch.setattr(
        daily_run, "_load_ohlcv",
        lambda symbol, asset_class, interval="1d": _synthetic_df(hash(symbol) % 1000),
    )

    class _StubSentiment:
        def get_crypto_fear_greed(self):
            return {"value": 50, "classification": "Neutral"}

    class _StubMacro:
        def get_dxy_and_yields_snapshot(self):
            return {}

    monkeypatch.setattr(daily_run, "SentimentProvider", _StubSentiment)
    monkeypatch.setattr(daily_run, "MacroProvider", _StubMacro)

    # "equity" market open, "taiwan" market closed, for this test only.
    monkeypatch.setattr(daily_run, "is_market_open", lambda asset_class: asset_class == "equity")
    return tmp_path


def test_first_run_analyzes_closed_market_symbol_anyway(tmp_path):
    """With no prior data at all, a closed-market symbol should still get
    analyzed once so the dashboard isn't empty for it forever."""
    payload = daily_run.run_daily_pipeline()
    symbols = {s["symbol"]: s for s in payload["signals"]}

    assert symbols["OPEN_SYM"]["market_open"] is True
    assert symbols["CLOSED_SYM"]["market_open"] is True  # no prior data -> analyzed anyway


def test_second_run_carries_forward_closed_market_symbol(tmp_path):
    """Once prior data exists, a closed-market symbol should be carried
    forward unchanged (aside from the market_open flag) instead of
    re-analyzed, while the open-market symbol keeps refreshing."""
    first = daily_run.run_daily_pipeline()
    first_closed_entry = next(s for s in first["signals"] if s["symbol"] == "CLOSED_SYM")

    second = daily_run.run_daily_pipeline()
    second_by_symbol = {s["symbol"]: s for s in second["signals"]}

    assert second_by_symbol["OPEN_SYM"]["market_open"] is True
    assert second_by_symbol["CLOSED_SYM"]["market_open"] is False
    # Carried-forward data should be identical to what the first run produced
    # (same price/signal), just re-tagged as not freshly analyzed.
    assert second_by_symbol["CLOSED_SYM"]["last_price"] == first_closed_entry["last_price"]
    assert second_by_symbol["CLOSED_SYM"]["as_of"] == first_closed_entry["as_of"]
