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
