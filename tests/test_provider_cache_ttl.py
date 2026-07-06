"""Regression guard for a subtle staleness bug: update_signals.yml now
self-chains as one long-lived job that loops internally every ~5 minutes
(see .github/workflows/update_signals.yml), rather than starting a fresh
VM (and therefore an empty on-disk cache) for every run like it used to.
If a provider's cache TTL is >= that loop interval, consecutive
iterations silently reuse the same stale price -- which showed up on the
dashboard as a stuck 0% change even while the market was clearly moving.
These tests just assert the default TTLs stay safely under 5 minutes so
this can't silently regress.
"""
from src.data.providers.ccxt_provider import CCXTProvider
from src.data.providers.yfinance_provider import YFinanceProvider

PIPELINE_LOOP_INTERVAL_SECONDS = 300  # `sleep 300` in update_signals.yml


def test_yfinance_provider_cache_ttl_shorter_than_pipeline_loop(tmp_path):
    provider = YFinanceProvider()
    assert provider.cache.ttl_seconds < PIPELINE_LOOP_INTERVAL_SECONDS


def test_ccxt_provider_cache_ttl_shorter_than_pipeline_loop():
    provider = CCXTProvider(use_cache=True)
    assert provider.cache.ttl_seconds < PIPELINE_LOOP_INTERVAL_SECONDS
