"""Tests for the Taiwan Weighted Index (加權股價指數, ^TWII) overall-market
snapshot -- per user request ("我是指大盤總共"), a single "is the whole
Taiwan market up or down today" figure distinct from any individual stock
pick, shown at the top of the dashboard.
"""
import numpy as np
import pandas as pd
import pytest

import src.pipeline.daily_run as daily_run


def _synthetic_df(seed: int, n: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    high, low = close * 1.005, close * 0.995
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume}, index=dates)


def test_fetch_taiex_snapshot_computes_change_from_prev_close(monkeypatch):
    df = pd.DataFrame({
        "open": [100.0, 101.0], "high": [101.0, 102.0], "low": [99.0, 100.0],
        "close": [17000.0, 17170.0], "volume": [1e9, 1e9],
    }, index=pd.date_range("2024-01-01", periods=2, freq="D"))
    monkeypatch.setattr(daily_run, "_load_ohlcv", lambda symbol, asset_class, interval="1d": df)
    monkeypatch.setattr(daily_run, "is_market_open", lambda asset_class: True)

    snapshot = daily_run._fetch_taiex_snapshot(None)

    assert snapshot["symbol"] == "^TWII"
    assert snapshot["price"] == 17170.0
    assert snapshot["change_pts"] == 170.0
    assert snapshot["change_pct"] == 1.0
    assert snapshot["market_open"] is True


def test_fetch_taiex_snapshot_carries_forward_when_market_closed(monkeypatch):
    monkeypatch.setattr(daily_run, "is_market_open", lambda asset_class: False)

    def _fail(*args, **kwargs):
        raise AssertionError("should not fetch fresh data when market is closed and prior data exists")
    monkeypatch.setattr(daily_run, "_load_ohlcv", _fail)

    previous = {"symbol": "^TWII", "price": 17170.0, "change_pct": 1.0, "change_pts": 170.0, "market_open": True}
    snapshot = daily_run._fetch_taiex_snapshot(previous)

    assert snapshot["price"] == 17170.0
    assert snapshot["market_open"] is False


def test_fetch_taiex_snapshot_falls_back_to_previous_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(daily_run, "is_market_open", lambda asset_class: True)

    def _fail(*args, **kwargs):
        raise ValueError("no data returned")
    monkeypatch.setattr(daily_run, "_load_ohlcv", _fail)

    previous = {"symbol": "^TWII", "price": 17170.0, "change_pct": 1.0, "change_pts": 170.0, "market_open": True}
    snapshot = daily_run._fetch_taiex_snapshot(previous)

    assert snapshot == previous


@pytest.fixture(autouse=True)
def _stub_pipeline_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_run, "DOCS_DATA_DIR", tmp_path)
    monkeypatch.setattr(daily_run, "WATCHLIST", {"taiwan": ["SYM"]})
    monkeypatch.setattr(daily_run, "PAIR_WATCHLIST", [])
    monkeypatch.setattr(daily_run, "_load_ohlcv", lambda symbol, asset_class, interval="1d": _synthetic_df(7))

    class _StubSentiment:
        def get_crypto_fear_greed(self):
            return {"value": 50, "classification": "Neutral"}

    class _StubMacro:
        def get_dxy_and_yields_snapshot(self):
            return {}

    monkeypatch.setattr(daily_run, "SentimentProvider", _StubSentiment)
    monkeypatch.setattr(daily_run, "MacroProvider", _StubMacro)
    monkeypatch.setattr(daily_run, "is_market_open", lambda asset_class: True)
    return tmp_path


def test_run_daily_pipeline_includes_taiex_snapshot():
    payload = daily_run.run_daily_pipeline()
    assert payload["taiex"] is not None
    assert payload["taiex"]["symbol"] == "^TWII"
    assert payload["taiex"]["change_pct"] is not None
