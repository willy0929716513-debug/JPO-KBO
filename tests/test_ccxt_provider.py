"""Binance's public REST API geo-blocks many cloud/datacenter IP ranges
(HTTP 451), which silently starved the crypto section of the dashboard for
days at a time (see git history of docs/data/signals_latest.json -- BTC/ETH
signals vanished with zero entries in `errors` for dozens of consecutive
runs). These tests verify CCXTProvider automatically falls back to other
exchanges rather than swallowing every failure into an empty DataFrame.
"""
import ccxt
import pandas as pd
import pytest

from src.data.providers.ccxt_provider import CCXTProvider


def _fake_ohlcv_rows(n=100):
    return [[1_700_000_000_000 + i * 86_400_000, 100 + i, 101 + i, 99 + i, 100.5 + i, 1000] for i in range(n)]


class _FakeExchange:
    def __init__(self, exchange_id, behavior):
        self.id = exchange_id
        self._behavior = behavior

    def fetch_ohlcv(self, symbol, timeframe=None, limit=None):
        if self._behavior == "raise":
            raise RuntimeError("451 Unavailable For Legal Reasons")
        if self._behavior == "empty":
            return []
        return _fake_ohlcv_rows()


def _patch_exchange(monkeypatch, exchange_id, behavior):
    monkeypatch.setattr(ccxt, exchange_id, lambda *_a, **_kw: _FakeExchange(exchange_id, behavior), raising=False)


def test_uses_primary_exchange_when_it_succeeds(monkeypatch):
    _patch_exchange(monkeypatch, "binance", "ok")
    _patch_exchange(monkeypatch, "okx", "raise")  # should never be called

    provider = CCXTProvider(use_cache=False)
    df = provider.get_ohlcv("BTC/USDT")

    assert not df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_falls_back_when_primary_raises(monkeypatch):
    _patch_exchange(monkeypatch, "binance", "raise")
    _patch_exchange(monkeypatch, "okx", "ok")
    _patch_exchange(monkeypatch, "bybit", "raise")
    _patch_exchange(monkeypatch, "kucoin", "raise")

    provider = CCXTProvider(use_cache=False)
    df = provider.get_ohlcv("BTC/USDT")

    assert not df.empty


def test_falls_back_when_primary_returns_empty_without_raising(monkeypatch):
    _patch_exchange(monkeypatch, "binance", "empty")
    _patch_exchange(monkeypatch, "okx", "ok")
    _patch_exchange(monkeypatch, "bybit", "raise")
    _patch_exchange(monkeypatch, "kucoin", "raise")

    provider = CCXTProvider(use_cache=False)
    df = provider.get_ohlcv("BTC/USDT")

    assert not df.empty


def test_returns_empty_dataframe_when_every_exchange_fails(monkeypatch):
    for exchange_id in ("binance", "okx", "bybit", "kucoin"):
        _patch_exchange(monkeypatch, exchange_id, "raise")

    provider = CCXTProvider(use_cache=False)
    df = provider.get_ohlcv("BTC/USDT")

    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
