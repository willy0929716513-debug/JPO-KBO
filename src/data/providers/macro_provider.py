"""Macro-economic data (CPI, PPI, Fed Funds Rate, Treasury yields, GDP,
unemployment, non-farm payroll) via the free FRED API.

Requires a free FRED_API_KEY (https://fred.stlouisfed.org/docs/api/api_key.html).
Without a key, methods return an empty DataFrame instead of raising, so the
rest of the pipeline keeps working.
"""
from __future__ import annotations

import logging

import pandas as pd
import requests

from src.config import Universe, settings

logger = logging.getLogger(__name__)

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


class MacroProvider:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.fred_api_key

    def get_series(self, series_id: str) -> pd.DataFrame:
        if not self.api_key:
            logger.info("FRED_API_KEY not set; skipping macro series %s", series_id)
            return pd.DataFrame(columns=["value"])
        try:
            resp = requests.get(
                FRED_URL,
                params={"series_id": series_id, "api_key": self.api_key, "file_type": "json"},
                timeout=15,
            )
            resp.raise_for_status()
            obs = resp.json().get("observations", [])
            df = pd.DataFrame(obs)
            if df.empty:
                return df
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            return df.set_index("date")[["value"]].dropna()
        except Exception as exc:
            logger.warning("FRED fetch failed for %s: %s", series_id, exc)
            return pd.DataFrame(columns=["value"])

    def get_all(self) -> dict[str, pd.DataFrame]:
        return {name: self.get_series(sid) for name, sid in Universe.MACRO_FRED_SERIES.items()}

    def get_dxy_and_yields_snapshot(self) -> dict[str, float | None]:
        """Convenience snapshot of the latest value for each configured macro series."""
        out: dict[str, float | None] = {}
        for name, df in self.get_all().items():
            out[name] = float(df["value"].iloc[-1]) if not df.empty else None
        return out
