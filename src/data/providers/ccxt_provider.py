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

    # Binance's public REST API geo-blocks many cloud/datacenter IP ranges
    # (HTTP 451 "Unavailable For Legal Reasons"), which includes GitHub
    # Actions' shared runners often enough that the crypto section of the
    # dashboard silently went empty for days at a time -- get_ohlcv used to
    # swallow the failure and return an empty frame with no visible error.
    # These exchanges expose the same public, no-key OHLCV endpoint for
    # BTC/USDT and ETH/USDT and are tried in order if the primary fails.
    _DEFAULT_FALLBACK_EXCHANGE_IDS = ("okx", "bybit", "kucoin")

    def __init__(self, exchange_id: str = "binance", use_cache: bool = True, cache_ttl_seconds: int = 300,
                 fallback_exchange_ids: tuple[str, ...] | None = None):
        import ccxt

        self._ccxt = ccxt
        self.exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self.cache = ParquetCache(ttl_seconds=cache_ttl_seconds) if use_cache else None
        fallback_ids = fallback_exchange_ids if fallback_exchange_ids is not None else self._DEFAULT_FALLBACK_EXCHANGE_IDS
        self._fallback_exchange_ids = [eid for eid in fallback_ids if eid != exchange_id]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _fetch_ohlcv(self, exchange, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        raw = exchange.fetch_ohlcv(symbol, timeframe=_TF_MAP.get(timeframe, timeframe), limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df.set_index("timestamp")

    def _candidate_exchanges(self):
        yield self.exchange.id, self.exchange
        for exchange_id in self._fallback_exchange_ids:
            yield exchange_id, getattr(self._ccxt, exchange_id)({"enableRateLimit": True})

    def get_ohlcv(self, symbol: str, interval: str = "1d", limit: int = 1000) -> pd.DataFrame:
        cache_key = f"ccxt_{self.exchange.id}_{symbol}_{interval}"
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        tried = []
        for exchange_id, exchange in self._candidate_exchanges():
            tried.append(exchange_id)
            try:
                df = self._fetch_ohlcv(exchange, symbol, interval, limit)
            except Exception as exc:
                logger.warning("ccxt fetch failed for %s/%s via %s: %s", symbol, interval, exchange_id, exc)
                continue
            if df.empty:
                continue
            if self.cache is not None:
                self.cache.set(cache_key, df)
            return df

        logger.warning("ccxt fetch failed for %s/%s on every exchange tried (%s)", symbol, interval, tried)
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

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
