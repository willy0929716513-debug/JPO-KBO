"""Free, no-API-key market data provider for equities, ETFs, metals,
energy futures and FX, backed by Yahoo Finance via the `yfinance` package.
"""
from __future__ import annotations

import logging

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data.cache import ParquetCache

logger = logging.getLogger(__name__)

_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "60m", "4h": "60m",  # yfinance has no native 4h; resample from 1h
    "1d": "1d", "1wk": "1wk", "1mo": "1mo",
}

_PERIOD_FOR_INTERVAL = {
    "1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d",
    "1h": "730d", "4h": "730d", "1d": "10y", "1wk": "max", "1mo": "max",
}


class YFinanceProvider:
    """Fetches OHLCV bars for stocks / ETF / gold / silver / oil / FX."""

    # Must stay shorter than the pipeline's own update cadence (every ~5
    # minutes, see .github/workflows/update_signals.yml). This cache was
    # originally harmless in production: every scheduled run used to start
    # on a brand-new GitHub Actions VM with an empty cache directory, so a
    # long TTL never actually got hit. Once update_signals.yml became a
    # single long-lived self-chaining job that loops internally with
    # `sleep 300` instead of restarting fresh each time, this on-disk cache
    # started persisting *within* that loop -- and the old 900s (15-minute)
    # TTL made 2-3 consecutive 5-minute loop iterations reuse the exact
    # same cached price, showing up on the dashboard as a stuck "0%"
    # change even while the market was clearly moving.
    def __init__(self, use_cache: bool = True, cache_ttl_seconds: int = 200):
        self.cache = ParquetCache(ttl_seconds=cache_ttl_seconds) if use_cache else None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _download(self, symbol: str, interval: str) -> pd.DataFrame:
        import yfinance as yf

        yf_interval = _INTERVAL_MAP.get(interval, interval)
        period = _PERIOD_FOR_INTERVAL.get(interval, "1y")
        df = yf.download(
            symbol, period=period, interval=yf_interval,
            auto_adjust=True, progress=False, multi_level_index=False,
        )
        if df is None or df.empty:
            raise ValueError(f"No data returned for {symbol} ({interval})")
        df = df.rename(columns=str.lower)
        df.index.name = "timestamp"

        if interval == "4h" and yf_interval == "60m":
            df = (
                df.resample("4h")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna()
            )
        return df[["open", "high", "low", "close", "volume"]]

    def get_ohlcv(self, symbol: str, interval: str = "1d") -> pd.DataFrame:
        cache_key = f"yf_{symbol}_{interval}"
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        try:
            df = self._download(symbol, interval)
        except Exception as exc:
            logger.warning("yfinance fetch failed for %s/%s: %s", symbol, interval, exc)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if self.cache is not None:
            self.cache.set(cache_key, df)
        return df

    def get_many(self, symbols: list[str], interval: str = "1d") -> dict[str, pd.DataFrame]:
        return {s: self.get_ohlcv(s, interval) for s in symbols}

    def get_multi_timeframe(self, symbol: str, timeframes: list[str]) -> dict[str, pd.DataFrame]:
        return {tf: self.get_ohlcv(symbol, tf) for tf in timeframes}
