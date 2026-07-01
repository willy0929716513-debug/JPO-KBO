import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_ohlcv() -> pd.DataFrame:
    """Deterministic synthetic OHLCV series (trending + noisy) for tests that
    must not depend on network access."""
    rng = np.random.default_rng(7)
    n = 400
    dates = pd.date_range("2023-01-01", periods=n, freq="D")

    drift = np.linspace(0, 0.4, n)
    noise = rng.normal(0, 0.015, n).cumsum()
    close = 100 * np.exp(drift + noise * 0.3)

    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)

    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=dates)
    df.index.name = "timestamp"
    return df


@pytest.fixture
def cointegrated_pair() -> tuple[pd.Series, pd.Series]:
    """Two synthetic price series sharing a common stochastic trend plus an
    independent mean-reverting spread -- genuinely cointegrated by construction."""
    rng = np.random.default_rng(11)
    n = 300
    dates = pd.date_range("2023-01-01", periods=n, freq="D")

    common_trend = np.cumsum(rng.normal(0.0005, 0.01, n))
    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = 0.7 * spread[t - 1] + rng.normal(0, 0.01)

    close_a = pd.Series(100 * np.exp(common_trend), index=dates)
    close_b = pd.Series(50 * np.exp(common_trend + spread), index=dates)
    return close_a, close_b


@pytest.fixture
def independent_pair() -> tuple[pd.Series, pd.Series]:
    """Two unrelated random-walk series that should NOT test as cointegrated."""
    rng = np.random.default_rng(13)
    n = 300
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    close_a = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n))), index=dates)
    close_b = pd.Series(50 * np.exp(np.cumsum(rng.normal(-0.0002, 0.012, n))), index=dates)
    return close_a, close_b
