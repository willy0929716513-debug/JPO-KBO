"""Verifies daily 漲跌幅 (percent change) is computed against the previous
trading day's close -- the convention every stock ticker/app uses -- not
against whatever price the last 5-minute poll happened to see. Comparing
consecutive polls used to show a meaningless "0%" most of the time once
free data sources' own ~15-20 minute refresh latency was accounted for
(see README).
"""
import numpy as np
import pandas as pd

import src.pipeline.daily_run as daily_run


def _synthetic_df(n: int = 400, last_close: float = 110.0, prev_close: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.008, n)))
    close[-2] = prev_close
    close[-1] = last_close
    high = close * 1.005
    low = close * 0.995
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                          "volume": rng.integers(1_000_000, 5_000_000, n).astype(float)}, index=dates)


def test_change_pct_uses_previous_close_not_last_row_only():
    df = _synthetic_df(last_close=110.0, prev_close=100.0)
    res = daily_run._analyze_symbol("TEST", "equity", df, macro_snapshot={}, sentiment_snapshot={})
    assert res["change_pct"] == 10.0


def test_change_pct_negative_when_price_fell():
    df = _synthetic_df(last_close=95.0, prev_close=100.0)
    res = daily_run._analyze_symbol("TEST", "equity", df, macro_snapshot={}, sentiment_snapshot={})
    assert res["change_pct"] == -5.0
