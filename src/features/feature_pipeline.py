"""Assembles the full feature matrix for a single symbol from raw OHLCV:
price/volume/volatility/momentum/trend indicators, market-structure flags,
rolling statistics, lag features, and calendar/session features.

Designed to comfortably grow past 300 columns as more `@register_feature`
functions are added (e.g. macro, options, sentiment, on-chain), without
having to touch the orchestration logic below.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.features import indicators as ta
from src.features import market_structure as ms
from src.features.registry import get_registry, register_feature


@register_feature("price_action")
def _price_action_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["ret_1"] = df["close"].pct_change(1)
    out["ret_5"] = df["close"].pct_change(5)
    out["ret_10"] = df["close"].pct_change(10)
    out["ret_20"] = df["close"].pct_change(20)
    out["log_ret_1"] = np.log(df["close"] / df["close"].shift(1))
    out["high_low_pct"] = (df["high"] - df["low"]) / df["close"]
    out["close_open_pct"] = (df["close"] - df["open"]) / df["open"]
    out["upper_wick_pct"] = (df["high"] - df[["open", "close"]].max(axis=1)) / df["close"]
    out["lower_wick_pct"] = (df[["open", "close"]].min(axis=1) - df["low"]) / df["close"]
    return out


@register_feature("trend")
def _trend_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for p in (10, 20, 50, 100, 200):
        if len(df) > p:
            out[f"sma_{p}"] = ta.sma(df["close"], p)
            out[f"ema_{p}"] = ta.ema(df["close"], p)
            out[f"close_over_sma_{p}"] = df["close"] / out[f"sma_{p}"] - 1
    macd_df = ta.macd(df["close"])
    out = pd.concat([out, macd_df.add_prefix("macd_")], axis=1)
    out = pd.concat([out, ta.adx(df)], axis=1)
    st = ta.supertrend(df)
    out["supertrend_dir"] = st["trend"]
    out["psar"] = ta.parabolic_sar(df)
    out["psar_above_close"] = (out["psar"] > df["close"]).astype(int)
    ichi = ta.ichimoku(df)
    out = pd.concat([out, ichi.add_prefix("ichimoku_")], axis=1)
    out["ichimoku_cloud_bull"] = (ichi["senkou_span_a"] > ichi["senkou_span_b"]).astype(int)
    return out


@register_feature("momentum")
def _momentum_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for p in (7, 14, 21):
        out[f"rsi_{p}"] = ta.rsi(df["close"], p)
    out = pd.concat([out, ta.stochastic(df)], axis=1)
    out["cci"] = ta.cci(df)
    out["mfi"] = ta.mfi(df)
    out["roc_10"] = ta.roc(df["close"], 10)
    return out


@register_feature("volatility")
def _volatility_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["atr_14"] = ta.atr(df, 14)
    out["atr_pct"] = out["atr_14"] / df["close"]
    out = pd.concat([out, ta.bollinger_bands(df["close"])], axis=1)
    out = pd.concat([out, ta.keltner_channel(df)], axis=1)
    out = pd.concat([out, ta.donchian_channel(df)], axis=1)
    out["realized_vol_20"] = df["close"].pct_change().rolling(20).std() * np.sqrt(252)
    out["realized_vol_60"] = df["close"].pct_change().rolling(60).std() * np.sqrt(252)
    return out


@register_feature("volume")
def _volume_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["obv"] = ta.obv(df)
    out["obv_slope"] = out["obv"].diff(5)
    out["volume_sma_20"] = ta.sma(df["volume"], 20)
    out["volume_ratio"] = df["volume"] / out["volume_sma_20"].replace(0, np.nan)
    out = pd.concat([out, ta.pivot_points(df)], axis=1)
    return out


@register_feature("market_structure")
def _market_structure_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    sw = ms.swing_points(df)
    out["swing_high"] = sw["swing_high"].astype(int)
    out["swing_low"] = sw["swing_low"].astype(int)
    bos = ms.break_of_structure(df)
    out["trend_direction"] = bos["trend_direction"]
    out["bos"] = bos["bos"].astype(int)
    out["choch"] = bos["choch"].astype(int)
    fvg = ms.fair_value_gaps(df)
    out["bullish_fvg"] = fvg["bullish_fvg"].astype(int)
    out["bearish_fvg"] = fvg["bearish_fvg"].astype(int)
    ob = ms.order_blocks(df)
    out["bullish_ob"] = ob["bullish_ob"].astype(int)
    out["bearish_ob"] = ob["bearish_ob"].astype(int)
    sweep = ms.liquidity_sweep(df)
    out["liquidity_sweep_high"] = sweep["liquidity_sweep_high"].astype(int)
    out["liquidity_sweep_low"] = sweep["liquidity_sweep_low"].astype(int)
    return out


@register_feature("time")
def _time_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    idx = df.index
    out["day_of_week"] = idx.dayofweek
    out["day_of_month"] = idx.day
    out["month"] = idx.month
    out["is_month_end"] = idx.is_month_end.astype(int)
    out["is_quarter_end"] = idx.is_quarter_end.astype(int)
    return out


def _add_lags_and_rolling(df: pd.DataFrame, cols: list[str], lags=(1, 2, 3, 5, 10)) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for col in cols:
        if col not in df.columns:
            continue
        for lag in lags:
            out[f"{col}_lag{lag}"] = df[col].shift(lag)
        out[f"{col}_roll_mean_10"] = df[col].rolling(10).mean()
        out[f"{col}_roll_std_10"] = df[col].rolling(10).std()
    return out


class FeaturePipeline:
    """Builds the full feature matrix for one symbol's OHLCV frame."""

    def __init__(self, lag_columns: list[str] | None = None):
        self.lag_columns = lag_columns or ["ret_1", "rsi_14", "atr_pct", "volume_ratio"]

    def build(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        blocks = [df[["open", "high", "low", "close", "volume"]]]
        for name, fn in get_registry().items():
            try:
                blocks.append(fn(df))
            except Exception:
                continue  # a single feature block failing shouldn't kill the pipeline
        features = pd.concat(blocks, axis=1)
        features = pd.concat([features, _add_lags_and_rolling(features, self.lag_columns)], axis=1)
        return features.loc[:, ~features.columns.duplicated()]

    @staticmethod
    def feature_count(features: pd.DataFrame) -> int:
        return len([c for c in features.columns if c not in ("open", "high", "low", "close", "volume")])
