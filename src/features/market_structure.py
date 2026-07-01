"""Simplified market-structure / Smart-Money-Concept (SMC) style features:
swing highs/lows, support & resistance clusters, break of structure (BOS),
change of character (CHoCH), fair value gaps (FVG), order blocks and
supply/demand zones.

These are pragmatic, rule-based approximations of discretionary SMC/ICT/Wyckoff
concepts -- useful as model features, not a claim of perfect concept fidelity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def swing_points(df: pd.DataFrame, lookback: int = 3) -> pd.DataFrame:
    """A bar is a swing high/low if it's the local extreme within +-lookback bars."""
    high, low = df["high"], df["low"]
    is_swing_high = high == high.rolling(2 * lookback + 1, center=True).max()
    is_swing_low = low == low.rolling(2 * lookback + 1, center=True).min()
    return pd.DataFrame({"swing_high": is_swing_high.fillna(False), "swing_low": is_swing_low.fillna(False)})


def support_resistance_levels(df: pd.DataFrame, lookback: int = 3, cluster_pct: float = 0.005) -> dict:
    """Cluster recent swing points into support/resistance price levels."""
    sw = swing_points(df, lookback)
    highs = df.loc[sw["swing_high"], "high"].to_numpy()
    lows = df.loc[sw["swing_low"], "low"].to_numpy()

    def cluster(levels: np.ndarray) -> list[float]:
        if len(levels) == 0:
            return []
        levels = np.sort(levels)
        clusters = [[levels[0]]]
        for lvl in levels[1:]:
            if abs(lvl - clusters[-1][-1]) / clusters[-1][-1] <= cluster_pct:
                clusters[-1].append(lvl)
            else:
                clusters.append([lvl])
        return [float(np.mean(c)) for c in clusters]

    return {"resistance": cluster(highs), "support": cluster(lows)}


def break_of_structure(df: pd.DataFrame, lookback: int = 3) -> pd.DataFrame:
    """BOS: close breaks beyond the most recent confirmed swing high/low in the
    direction of the prevailing trend. CHoCH: break in the *opposite* direction
    of the prevailing trend, signalling a potential trend reversal.
    """
    sw = swing_points(df, lookback)
    last_swing_high = df["high"].where(sw["swing_high"]).ffill()
    last_swing_low = df["low"].where(sw["swing_low"]).ffill()

    bullish_break = df["close"] > last_swing_high.shift(1)
    bearish_break = df["close"] < last_swing_low.shift(1)

    trend = pd.Series(0, index=df.index)
    trend[bullish_break] = 1
    trend[bearish_break] = -1
    trend = trend.replace(0, np.nan).ffill().fillna(0)

    prev_trend = trend.shift(1).fillna(0)
    bos = ((trend == 1) & (prev_trend == 1)) | ((trend == -1) & (prev_trend == -1))
    choch = (trend != prev_trend) & (prev_trend != 0)

    return pd.DataFrame({
        "trend_direction": trend, "bos": bos & (bullish_break | bearish_break),
        "choch": choch, "bullish_break": bullish_break, "bearish_break": bearish_break,
    })


def fair_value_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """3-candle imbalance: gap between candle[i-1].high/low and candle[i+1].low/high
    with candle[i] as the impulse candle."""
    high, low = df["high"], df["low"]
    bullish_fvg = low.shift(-1) > high.shift(1)
    bearish_fvg = high.shift(-1) < low.shift(1)
    gap_top = np.where(bullish_fvg, low.shift(-1), np.where(bearish_fvg, low.shift(1), np.nan))
    gap_bottom = np.where(bullish_fvg, high.shift(1), np.where(bearish_fvg, high.shift(-1), np.nan))
    return pd.DataFrame({
        "bullish_fvg": bullish_fvg.fillna(False), "bearish_fvg": bearish_fvg.fillna(False),
        "fvg_top": gap_top, "fvg_bottom": gap_bottom,
    }, index=df.index)


def order_blocks(df: pd.DataFrame, lookback: int = 3) -> pd.DataFrame:
    """Approximate order block: last down-candle before a strong up-move that
    breaks structure (bullish OB), or last up-candle before a strong down-move
    that breaks structure (bearish OB)."""
    bos_df = break_of_structure(df, lookback)
    bullish_candle = df["close"] > df["open"]
    bearish_candle = df["close"] < df["open"]

    bullish_ob = bearish_candle.shift(1).fillna(False) & bos_df["bullish_break"]
    bearish_ob = bullish_candle.shift(1).fillna(False) & bos_df["bearish_break"]

    return pd.DataFrame({
        "bullish_ob": bullish_ob, "bearish_ob": bearish_ob,
        "bullish_ob_high": df["high"].shift(1).where(bullish_ob),
        "bullish_ob_low": df["low"].shift(1).where(bullish_ob),
        "bearish_ob_high": df["high"].shift(1).where(bearish_ob),
        "bearish_ob_low": df["low"].shift(1).where(bearish_ob),
    })


def liquidity_sweep(df: pd.DataFrame, lookback: int = 10) -> pd.DataFrame:
    """Price wicks beyond a recent high/low then closes back inside it -- a
    classic 'stop hunt' / liquidity grab pattern."""
    rolling_high = df["high"].rolling(lookback).max().shift(1)
    rolling_low = df["low"].rolling(lookback).min().shift(1)
    sweep_high = (df["high"] > rolling_high) & (df["close"] < rolling_high)
    sweep_low = (df["low"] < rolling_low) & (df["close"] > rolling_low)
    return pd.DataFrame({"liquidity_sweep_high": sweep_high, "liquidity_sweep_low": sweep_low})


def supply_demand_zones(df: pd.DataFrame, lookback: int = 3, atr_mult: float = 1.5) -> dict:
    """Zones built around order blocks, widened by ATR for a realistic band."""
    from src.features.indicators import atr as atr_fn

    ob = order_blocks(df, lookback)
    atr_series = atr_fn(df)
    demand = []
    supply = []
    for i in df.index[ob["bullish_ob"]]:
        a = atr_series.loc[i] if not np.isnan(atr_series.loc[i]) else 0
        demand.append({"low": float(ob.loc[i, "bullish_ob_low"] - a * atr_mult * 0.1),
                        "high": float(ob.loc[i, "bullish_ob_high"])})
    for i in df.index[ob["bearish_ob"]]:
        a = atr_series.loc[i] if not np.isnan(atr_series.loc[i]) else 0
        supply.append({"low": float(ob.loc[i, "bearish_ob_low"]),
                        "high": float(ob.loc[i, "bearish_ob_high"] + a * atr_mult * 0.1)})
    return {"demand_zones": demand[-10:], "supply_zones": supply[-10:]}
