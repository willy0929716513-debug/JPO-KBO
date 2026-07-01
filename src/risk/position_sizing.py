"""Position sizing methods: Kelly criterion, fixed fractional, and
ATR-based (volatility-normalized) sizing."""
from __future__ import annotations

import numpy as np


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float, kelly_cap: float = 0.5) -> float:
    """Classic Kelly criterion: f* = W - (1-W)/R, where R = avg_win/avg_loss.
    `kelly_cap` fractionalizes the result (e.g. 0.5 = "half Kelly") since full
    Kelly is high-variance in practice.
    """
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0
    r = avg_win / avg_loss
    f_star = win_rate - (1 - win_rate) / r
    return float(np.clip(f_star, 0.0, 1.0) * kelly_cap)


def fixed_fractional_size(capital: float, risk_pct: float, entry_price: float, stop_price: float) -> float:
    """Position size (# of units) such that a stop-out loses exactly
    `risk_pct` of `capital`."""
    risk_per_unit = abs(entry_price - stop_price)
    if risk_per_unit <= 0:
        return 0.0
    dollar_risk = capital * risk_pct
    return dollar_risk / risk_per_unit


def atr_based_size(capital: float, risk_pct: float, atr: float, atr_multiplier: float = 2.0) -> float:
    """Position size (# of units) sized so that an `atr_multiplier`-ATR
    adverse move loses `risk_pct` of capital -- self-adjusts to volatility."""
    stop_distance = atr * atr_multiplier
    if stop_distance <= 0:
        return 0.0
    return (capital * risk_pct) / stop_distance


def volatility_target_weight(target_annual_vol: float, asset_annual_vol: float, max_weight: float = 1.0) -> float:
    """Scales an asset's portfolio weight so its contribution to volatility
    matches `target_annual_vol` (simple inverse-vol targeting)."""
    if asset_annual_vol <= 0:
        return 0.0
    return float(np.clip(target_annual_vol / asset_annual_vol, 0.0, max_weight))
