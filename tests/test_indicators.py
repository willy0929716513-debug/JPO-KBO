import numpy as np

from src.features import indicators as ta


def test_sma_ema_basic(synthetic_ohlcv):
    close = synthetic_ohlcv["close"]
    sma20 = ta.sma(close, 20)
    ema20 = ta.ema(close, 20)
    assert sma20.notna().sum() > 0
    assert ema20.notna().sum() > 0
    assert len(sma20) == len(close)


def test_rsi_bounds(synthetic_ohlcv):
    rsi = ta.rsi(synthetic_ohlcv["close"])
    valid = rsi.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_macd_shape(synthetic_ohlcv):
    macd_df = ta.macd(synthetic_ohlcv["close"])
    assert set(["macd", "signal", "hist"]).issubset(macd_df.columns)


def test_atr_positive(synthetic_ohlcv):
    atr = ta.atr(synthetic_ohlcv)
    assert (atr.dropna() >= 0).all()


def test_bollinger_band_ordering(synthetic_ohlcv):
    bb = ta.bollinger_bands(synthetic_ohlcv["close"])
    valid = bb.dropna()
    assert (valid["bb_upper"] >= valid["bb_mid"]).all()
    assert (valid["bb_mid"] >= valid["bb_lower"]).all()


def test_supertrend_runs(synthetic_ohlcv):
    st = ta.supertrend(synthetic_ohlcv)
    assert st["trend"].isin([1, -1]).all()


def test_adx_range(synthetic_ohlcv):
    adx_df = ta.adx(synthetic_ohlcv)
    valid = adx_df["adx"].dropna()
    assert (valid >= 0).all() and (valid <= 100).all()
