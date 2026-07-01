"""Market regime detection: classifies the current market as bull/bear/range
and high/low volatility, so the strategy engine can switch or weight
strategies appropriately (trend-following in trending regimes, mean-reversion
in ranging regimes, reduced size in high-volatility regimes).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from src.features.indicators import adx, atr, ema


class MarketRegime(str, Enum):
    BULL_TREND = "bull_trend"
    BEAR_TREND = "bear_trend"
    RANGE_BOUND = "range_bound"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


@dataclass
class RegimeState:
    regime: MarketRegime
    trend_strength: float  # ADX value
    volatility_percentile: float  # 0-1, realized vol percentile over lookback
    direction: int  # 1 bull, -1 bear, 0 neutral


class RegimeDetector:
    def __init__(self, adx_trend_threshold: float = 22.0, vol_lookback: int = 252):
        self.adx_trend_threshold = adx_trend_threshold
        self.vol_lookback = vol_lookback

    def detect(self, df: pd.DataFrame) -> RegimeState:
        if len(df) < 60:
            return RegimeState(MarketRegime.UNKNOWN, 0.0, 0.5, 0)

        adx_df = adx(df)
        adx_val = float(adx_df["adx"].iloc[-1]) if not pd.isna(adx_df["adx"].iloc[-1]) else 0.0
        direction = 1 if adx_df["plus_di"].iloc[-1] > adx_df["minus_di"].iloc[-1] else -1

        ema_fast = ema(df["close"], 20).iloc[-1]
        ema_slow = ema(df["close"], 50).iloc[-1]

        realized_vol = df["close"].pct_change().rolling(20).std()
        lookback = realized_vol.tail(self.vol_lookback).dropna()
        vol_percentile = 0.5
        if len(lookback) > 20:
            vol_percentile = float((lookback <= lookback.iloc[-1]).mean())

        if vol_percentile >= 0.85:
            regime = MarketRegime.HIGH_VOLATILITY
        elif adx_val >= self.adx_trend_threshold and ema_fast > ema_slow:
            regime = MarketRegime.BULL_TREND
        elif adx_val >= self.adx_trend_threshold and ema_fast < ema_slow:
            regime = MarketRegime.BEAR_TREND
        elif vol_percentile <= 0.15:
            regime = MarketRegime.LOW_VOLATILITY
        else:
            regime = MarketRegime.RANGE_BOUND

        return RegimeState(regime, round(adx_val, 2), round(vol_percentile, 3), direction)
