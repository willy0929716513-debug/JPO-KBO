"""Multi-timeframe trend alignment: checks whether short/medium/long
timeframes agree on trend direction, which is a strong regime/confidence
filter used across most strategies in this system.
"""
from __future__ import annotations

import pandas as pd

from src.features.indicators import adx, ema


def timeframe_trend(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> int:
    """Returns 1 (uptrend), -1 (downtrend) or 0 (no clear trend) for a single
    timeframe's OHLCV frame, using EMA cross + ADX strength filter."""
    if len(df) < slow + 1:
        return 0
    fast_ema = ema(df["close"], fast).iloc[-1]
    slow_ema = ema(df["close"], slow).iloc[-1]
    adx_val = adx(df).iloc[-1]["adx"]
    if pd.isna(fast_ema) or pd.isna(slow_ema) or pd.isna(adx_val):
        return 0
    if adx_val < 15:
        return 0  # too weak / ranging
    return 1 if fast_ema > slow_ema else -1


def multi_timeframe_alignment(frames: dict[str, pd.DataFrame]) -> dict:
    """`frames` maps timeframe label -> OHLCV DataFrame (e.g. {'1h': df1h, '4h': df4h, '1d': df1d}).
    Returns per-timeframe trend plus an overall alignment score in [-1, 1].
    """
    trends = {tf: timeframe_trend(df) for tf, df in frames.items() if not df.empty}
    if not trends:
        return {"trends": {}, "alignment_score": 0.0, "aligned": False}
    score = sum(trends.values()) / len(trends)
    aligned = all(v == trends[next(iter(trends))] for v in trends.values()) and score != 0
    return {"trends": trends, "alignment_score": round(score, 3), "aligned": aligned}
