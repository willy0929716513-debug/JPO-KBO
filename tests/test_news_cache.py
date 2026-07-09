"""Regression guard for src.data.providers.yfinance_provider.YFinanceProvider.get_news():
news needs its own, much longer-lived cache than OHLCV price data. Unlike
price caching (which must stay under the pipeline's 5-minute loop interval
to avoid a stuck "0% change" bug -- see test_provider_cache_ttl.py), news
caching should stay ABOVE that interval: headlines don't change every 5
minutes, and get_news() is now called for every symbol on every tick
regardless of market hours (see daily_run.py), so a short-lived cache here
would defeat the point and multiply real API calls for no benefit.
"""
import pytest

from src.data.providers.yfinance_provider import YFinanceProvider

PIPELINE_LOOP_INTERVAL_SECONDS = 300  # `sleep 300` in update_signals.yml


class _FakeTicker:
    call_count = 0

    def __init__(self, symbol):
        self.symbol = symbol

    @property
    def news(self):
        _FakeTicker.call_count += 1
        return [{"content": {"title": f"Headline #{_FakeTicker.call_count}",
                              "canonicalUrl": {"url": "https://example.com/a"}}}]


@pytest.fixture(autouse=True)
def _reset_fake_ticker_calls():
    _FakeTicker.call_count = 0
    yield


def test_news_cache_ttl_is_at_least_the_pipeline_loop_interval(tmp_path):
    provider = YFinanceProvider()
    assert provider.news_cache.ttl_seconds >= PIPELINE_LOOP_INTERVAL_SECONDS


def test_get_news_uses_its_own_cache_distinct_from_price_cache(tmp_path):
    provider = YFinanceProvider()
    assert provider.news_cache is not provider.cache
    assert provider.news_cache.ttl_seconds != provider.cache.ttl_seconds


def test_get_news_is_cached_across_calls(tmp_path, monkeypatch):
    monkeypatch.setattr("yfinance.Ticker", _FakeTicker)
    provider = YFinanceProvider()
    provider.news_cache.root = tmp_path

    first = provider.get_news("FAKE_SYM")
    second = provider.get_news("FAKE_SYM")

    assert first == second
    assert _FakeTicker.call_count == 1  # second call hit the cache, no new fetch


def test_get_news_cache_is_keyed_per_symbol(tmp_path, monkeypatch):
    monkeypatch.setattr("yfinance.Ticker", _FakeTicker)
    provider = YFinanceProvider()
    provider.news_cache.root = tmp_path

    provider.get_news("SYM_A")
    provider.get_news("SYM_B")

    assert _FakeTicker.call_count == 2  # different symbols must not share a cache entry
