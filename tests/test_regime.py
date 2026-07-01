from src.regime import MarketRegime, RegimeDetector


def test_regime_detector_returns_valid_state(synthetic_ohlcv):
    state = RegimeDetector().detect(synthetic_ohlcv)
    assert isinstance(state.regime, MarketRegime)
    assert 0.0 <= state.volatility_percentile <= 1.0
    assert state.direction in (1, -1)


def test_regime_detector_handles_short_series():
    import pandas as pd
    tiny = pd.DataFrame({"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2], "volume": [1, 1]})
    state = RegimeDetector().detect(tiny)
    assert state.regime == MarketRegime.UNKNOWN
