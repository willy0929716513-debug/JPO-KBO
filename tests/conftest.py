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
