"""Crypto market data via CCXT public REST endpoints (no API key required
for OHLCV / order book / funding rate / open interest on most exchanges).
"""
from __future__ import annotations

import logging

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data.cache import ParquetCache

logger = logging.getLogger(__name__)

_TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1wk": "1w",
}


class CCXTProvider:
    """Fetches OHLCV, order book snapshots, funding rate and open interest
    for crypto perpetual/spot markets. Defaults to Binance's public API.
    """

    def __init__(self, exchange_id: str = "binance", use_cache: bool = True, cache_ttl_seconds: int = 300):
        import ccxt

        self.exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self.cache = ParquetCache(ttl_seconds=cache_ttl_seconds) if use_cache else None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        raw = self.exchange.fetch_ohlcv(symbol, timeframe=_TF_MAP.get(timeframe, timeframe), limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df.set_index("timestamp")

    def get_ohlcv(self, symbol: str, interval: str = "1d", limit: int = 1000) -> pd.DataFrame:
        cache_key = f"ccxt_{self.exchange.id}_{symbol}_{interval}"
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        try:
            df = self._fetch_ohlcv(symbol, interval, limit)
        except Exception as exc:
            logger.warning("ccxt fetch failed for %s/%s: %s", symbol, interval, exc)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if self.cache is not None:
            self.cache.set(cache_key, df)
        return df

    def get_order_book(self, symbol: str, depth: int = 50) -> dict:
        try:
            return self.exchange.fetch_order_book(symbol, limit=depth)
        except Exception as exc:
            logger.warning("order book fetch failed for %s: %s", symbol, exc)
            return {"bids": [], "asks": []}

    def get_funding_rate(self, symbol: str) -> float | None:
        """Perpetual futures funding rate. Only meaningful for symbols
        listed on the exchange's futures market (e.g. 'BTC/USDT:USDT')."""
        try:
            if not self.exchange.has.get("fetchFundingRate"):
                return None
            data = self.exchange.fetch_funding_rate(symbol)
            return data.get("fundingRate")
        except Exception as exc:
            logger.warning("funding rate fetch failed for %s: %s", symbol, exc)
            return None

    def get_open_interest(self, symbol: str) -> float | None:
        try:
            if not self.exchange.has.get("fetchOpenInterest"):
                return None
            data = self.exchange.fetch_open_interest(symbol)
            return data.get("openInterestAmount") or data.get("openInterestValue")
        except Exception as exc:
            logger.warning("open interest fetch failed for %s: %s", symbol, exc)
            return None

    def get_many(self, symbols: list[str], interval: str = "1d") -> dict[str, pd.DataFrame]:
        return {s: self.get_ohlcv(s, interval) for s in symbols}
