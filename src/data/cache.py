"""Lightweight local cache for OHLCV frames, keyed by symbol/timeframe.

Uses Parquet so repeated backtests/feature builds don't re-hit network APIs.
Falls back to CSV automatically if pyarrow isn't installed.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from src.config import CACHE_DIR_DEFAULT


class ParquetCache:
    def __init__(self, root: Path | None = None, ttl_seconds: int = 3600):
        self.root = root or CACHE_DIR_DEFAULT
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    def _path(self, key: str) -> Path:
        safe = key.replace("/", "_").replace("=", "_").replace(" ", "_")
        return self.root / f"{safe}.parquet"

    def get(self, key: str) -> pd.DataFrame | None:
        path = self._path(key)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.ttl_seconds:
            return None
        try:
            return pd.read_parquet(path)
        except Exception:
            return None

    def set(self, key: str, df: pd.DataFrame) -> None:
        try:
            df.to_parquet(self._path(key))
        except Exception:
            df.to_csv(self._path(key).with_suffix(".csv"))
