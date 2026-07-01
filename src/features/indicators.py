"""Self-contained technical indicator library (no external TA dependency,
so it never breaks on numpy/pandas version drift).

Every function takes/returns pandas Series or a DataFrame with at least
`open, high, low, close, volume` columns, and is pure (no lookahead bias:
each indicator at row t only uses data up to and including row t).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- trend ----
def sma(series: pd.Series, period: int = 20) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int = 20) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema, slow_ema = ema(series, fast), ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    up_move, down_move = high.diff(), -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = true_range(df)
    atr_ = pd.Series(tr, index=df.index).ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, min_periods=period).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, min_periods=period).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_ = dx.ewm(alpha=1 / period, min_periods=period).mean()
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "adx": adx_})


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    kijun_sen = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2
    span_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
    span_b = ((high.rolling(senkou_b).max() + low.rolling(senkou_b).min()) / 2).shift(kijun)
    chikou = close.shift(-kijun)
    return pd.DataFrame({
        "tenkan_sen": tenkan_sen, "kijun_sen": kijun_sen,
        "senkou_span_a": span_a, "senkou_span_b": span_b, "chikou_span": chikou,
    })


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    atr_ = atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upper_basic = hl2 + multiplier * atr_
    lower_basic = hl2 - multiplier * atr_

    final_upper = upper_basic.copy()
    final_lower = lower_basic.copy()
    trend = pd.Series(1, index=df.index)

    close = df["close"]
    for i in range(1, len(df)):
        if close.iloc[i - 1] <= final_upper.iloc[i - 1]:
            final_upper.iloc[i] = min(upper_basic.iloc[i], final_upper.iloc[i - 1])
        else:
            final_upper.iloc[i] = upper_basic.iloc[i]

        if close.iloc[i - 1] >= final_lower.iloc[i - 1]:
            final_lower.iloc[i] = max(lower_basic.iloc[i], final_lower.iloc[i - 1])
        else:
            final_lower.iloc[i] = lower_basic.iloc[i]

        if close.iloc[i] > final_upper.iloc[i - 1]:
            trend.iloc[i] = 1
        elif close.iloc[i] < final_lower.iloc[i - 1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i - 1]

    supertrend_line = np.where(trend == 1, final_lower, final_upper)
    return pd.DataFrame({"supertrend": supertrend_line, "trend": trend}, index=df.index)


def parabolic_sar(df: pd.DataFrame, af_step: float = 0.02, af_max: float = 0.2) -> pd.Series:
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    sar = np.zeros(n)
    trend_up = True
    af = af_step
    ep = low[0]
    sar[0] = high[0]

    for i in range(1, n):
        sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
        if trend_up:
            sar[i] = min(sar[i], low[i - 1], low[max(i - 2, 0)])
            if high[i] > ep:
                ep = high[i]
                af = min(af + af_step, af_max)
            if low[i] < sar[i]:
                trend_up = False
                sar[i] = ep
                ep = low[i]
                af = af_step
        else:
            sar[i] = max(sar[i], high[i - 1], high[max(i - 2, 0)])
            if low[i] < ep:
                ep = low[i]
                af = min(af + af_step, af_max)
            if high[i] > sar[i]:
                trend_up = True
                sar[i] = ep
                ep = high[i]
                af = af_step
    return pd.Series(sar, index=df.index, name="psar")


# ------------------------------------------------------------ momentum ----
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    k = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return pd.DataFrame({"stoch_k": k, "stoch_d": d})


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma_tp) / (0.015 * mad.replace(0, np.nan))


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    raw_flow = tp * df["volume"]
    positive_flow = raw_flow.where(tp.diff() > 0, 0.0).rolling(period).sum()
    negative_flow = raw_flow.where(tp.diff() < 0, 0.0).rolling(period).sum()
    ratio = positive_flow / negative_flow.replace(0, np.nan)
    return 100 - (100 / (1 + ratio))


def roc(series: pd.Series, period: int = 10) -> pd.Series:
    return series.pct_change(period) * 100


# ------------------------------------------------------------ volatility ----
def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, min_periods=period).mean()


def bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(series, period)
    std = series.rolling(period).std()
    return pd.DataFrame({
        "bb_mid": mid, "bb_upper": mid + num_std * std, "bb_lower": mid - num_std * std,
        "bb_width": (num_std * std * 2) / mid,
    })


def keltner_channel(df: pd.DataFrame, period: int = 20, atr_mult: float = 2.0) -> pd.DataFrame:
    mid = ema(df["close"], period)
    atr_ = atr(df, period)
    return pd.DataFrame({
        "kc_mid": mid, "kc_upper": mid + atr_mult * atr_, "kc_lower": mid - atr_mult * atr_,
    })


def donchian_channel(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    upper = df["high"].rolling(period).max()
    lower = df["low"].rolling(period).min()
    return pd.DataFrame({"dc_upper": upper, "dc_lower": lower, "dc_mid": (upper + lower) / 2})


# ---------------------------------------------------------------- volume ----
def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0))
    return (direction * df["volume"]).cumsum()


def vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return (tp * df["volume"]).cumsum() / df["volume"].cumsum()


def anchored_vwap(df: pd.DataFrame, anchor_idx: int) -> pd.Series:
    sub = df.iloc[anchor_idx:]
    tp = (sub["high"] + sub["low"] + sub["close"]) / 3
    av = (tp * sub["volume"]).cumsum() / sub["volume"].cumsum()
    return av.reindex(df.index)


def volume_profile(df: pd.DataFrame, bins: int = 24) -> pd.DataFrame:
    """Approximate volume-at-price profile over the whole window."""
    price = (df["high"] + df["low"] + df["close"]) / 3
    hist, edges = np.histogram(price, bins=bins, weights=df["volume"])
    poc_idx = int(np.argmax(hist))
    return pd.DataFrame({
        "price_low": edges[:-1], "price_high": edges[1:], "volume": hist,
        "is_poc": [i == poc_idx for i in range(bins)],
    })


def pivot_points(df: pd.DataFrame) -> pd.DataFrame:
    """Classic floor-trader pivots computed from the prior bar's H/L/C."""
    prev_high, prev_low, prev_close = df["high"].shift(1), df["low"].shift(1), df["close"].shift(1)
    pivot = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * pivot - prev_low
    s1 = 2 * pivot - prev_high
    r2 = pivot + (prev_high - prev_low)
    s2 = pivot - (prev_high - prev_low)
    return pd.DataFrame({"pivot": pivot, "r1": r1, "s1": s1, "r2": r2, "s2": s2})


ALL_INDICATOR_NAMES = [
    "sma", "ema", "macd", "adx", "ichimoku", "supertrend", "parabolic_sar",
    "rsi", "stochastic", "cci", "mfi", "roc",
    "atr", "bollinger_bands", "keltner_channel", "donchian_channel",
    "obv", "vwap", "anchored_vwap", "volume_profile", "pivot_points",
]
