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

    # Deterministic, offline stand-in for news -- every call returns a
    # fresh (incrementing) headline so tests can tell whether a symbol's
    # news actually got refreshed on a given run, without ever hitting the
    # real yfinance news endpoint (this repo's sandbox has no network
    # access, and even where it does, tests shouldn't depend on live data).
    news_call_count = {"n": 0}

    def _fake_load_news_with_sentiment(symbol, asset_class):
        news_call_count["n"] += 1
        news = [{"title": f"headline {news_call_count['n']}", "link": "https://example.com",
                 "publisher": "Test Wire", "published_at": None}]
        return news, {"score": 0.0, "bullish_count": 0, "bearish_count": 0}

    monkeypatch.setattr(daily_run, "_load_news_with_sentiment", _fake_load_news_with_sentiment)

    # "equity" market open, "taiwan" market closed, for this test only.
    monkeypatch.setattr(daily_run, "is_market_open", lambda asset_class: asset_class == "equity")
    return tmp_path


def test_first_run_analyzes_closed_market_symbol_anyway(tmp_path):
    """With no prior data at all, a closed-market symbol should still get
    analyzed once so the dashboard isn't empty for it forever -- but its
    market_open flag must still honestly reflect that the market is
    actually closed. Being freshly analyzed for the first time doesn't
    make a closed market open; an earlier version of this code hardcoded
    market_open=True for any freshly-analyzed symbol, which mislabeled
    brand-new watchlist additions as "open" even on a day their market was
    genuinely closed."""
    payload = daily_run.run_daily_pipeline()
    symbols = {s["symbol"]: s for s in payload["signals"]}

    assert symbols["OPEN_SYM"]["market_open"] is True
    assert symbols["CLOSED_SYM"]["market_open"] is False  # freshly analyzed, but market is genuinely closed


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


def test_closed_market_symbol_still_refreshes_its_news_every_run():
    """Regression test: news/news_sentiment must NOT be frozen along with
    price/technicals for a closed-market symbol. Headlines get published
    around the clock regardless of trading hours -- freezing them here made
    Taiwan stocks (market open only ~4.5h/weekday) almost never refresh
    their news score, making them nearly invisible on the "📰 新聞熱門股"
    page despite being this project's primary focus (real user report)."""
    first = daily_run.run_daily_pipeline()
    first_closed_entry = next(s for s in first["signals"] if s["symbol"] == "CLOSED_SYM")

    second = daily_run.run_daily_pipeline()
    second_closed_entry = next(s for s in second["signals"] if s["symbol"] == "CLOSED_SYM")

    assert second_closed_entry["market_open"] is False
    # Price/as_of are frozen (verified above), but the news headline (from
    # the incrementing fake stub) must differ between runs.
    assert second_closed_entry["news"][0]["title"] != first_closed_entry["news"][0]["title"]
    assert "news_sentiment" in second_closed_entry
