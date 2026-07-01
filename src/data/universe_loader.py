"""High-level helper that fetches OHLCV for the whole configured universe
(equities, ETF, metals, energy, FX via yfinance; crypto via ccxt) in one call.
"""
from __future__ import annotations

import pandas as pd

from src.config import Universe
from src.data.providers.ccxt_provider import CCXTProvider
from src.data.providers.yfinance_provider import YFinanceProvider


def fetch_universe_ohlcv(interval: str = "1d") -> dict[str, pd.DataFrame]:
    """Returns {symbol: ohlcv_dataframe} for every asset class in Universe."""
    result: dict[str, pd.DataFrame] = {}

    yf = YFinanceProvider()
    result.update(yf.get_many(Universe.all_yfinance_symbols(), interval=interval))

    try:
        cx = CCXTProvider()
        result.update(cx.get_many(Universe.CRYPTO, interval=interval))
    except Exception:
        pass  # ccxt/exchange unreachable (e.g. offline CI sandbox); skip crypto silently

    return {k: v for k, v in result.items() if v is not None and not v.empty}
