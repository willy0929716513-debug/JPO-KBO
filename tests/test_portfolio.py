import numpy as np
import pandas as pd

from src.portfolio.allocator import PortfolioAllocator


def test_equal_weight_normalizes():
    allocator = PortfolioAllocator(max_position_weight=0.5)
    weights = allocator.equal_weight(["AAPL", "BTC/USDT", "GLD"])
    assert abs(sum(weights.values()) - 1.0) < 1e-3


def test_inverse_volatility_weighting():
    allocator = PortfolioAllocator()
    returns = {
        "low_vol": pd.Series([0.001, -0.001, 0.002, -0.0005]),
        "high_vol": pd.Series([0.05, -0.06, 0.04, -0.05]),
    }
    weights = allocator.inverse_volatility(returns)
    assert weights["low_vol"] > weights["high_vol"]


def test_asset_class_caps():
    allocator = PortfolioAllocator(max_asset_class_weight=0.4)
    weights = {"BTC/USDT": 0.5, "ETH/USDT": 0.3, "AAPL": 0.2}
    asset_class_of = {"BTC/USDT": "crypto", "ETH/USDT": "crypto", "AAPL": "equity"}
    capped = allocator.apply_asset_class_caps(weights, asset_class_of)
    crypto_total = capped["BTC/USDT"] + capped["ETH/USDT"]
    assert crypto_total <= 0.41


def test_risk_parity_sums_to_one():
    allocator = PortfolioAllocator(max_position_weight=1.0)
    rng = np.random.default_rng(5)
    returns = {
        "A": pd.Series(rng.normal(0, 0.01, 200)),
        "B": pd.Series(rng.normal(0, 0.02, 200)),
        "C": pd.Series(rng.normal(0, 0.03, 200)),
    }
    weights = allocator.risk_parity(returns)
    assert abs(sum(weights.values()) - 1.0) < 1e-3
    assert all(w >= 0 for w in weights.values())


def test_risk_parity_downweights_higher_volatility_asset():
    allocator = PortfolioAllocator(max_position_weight=1.0)
    rng = np.random.default_rng(5)
    returns = {
        "low_vol": pd.Series(rng.normal(0, 0.005, 300)),
        "high_vol": pd.Series(rng.normal(0, 0.05, 300)),
    }
    weights = allocator.risk_parity(returns)
    assert weights["low_vol"] > weights["high_vol"]


def test_risk_parity_single_asset():
    allocator = PortfolioAllocator()
    weights = allocator.risk_parity({"A": pd.Series([0.01, -0.01, 0.02])})
    assert weights == {"A": 1.0}
