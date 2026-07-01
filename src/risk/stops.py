"""Stop-loss / take-profit calculators: static ATR stop, trailing stop, and
dynamic take-profit based on the current volatility regime."""
from __future__ import annotations

import pandas as pd


def atr_stop(entry_price: float, atr: float, direction: int, multiplier: float = 2.0) -> float:
    """direction: 1 = long, -1 = short."""
    return entry_price - direction * atr * multiplier


def dynamic_take_profit(entry_price: float, atr: float, direction: int, reward_risk_ratio: float = 2.0,
                         stop_multiplier: float = 2.0) -> float:
    stop_distance = atr * stop_multiplier
    return entry_price + direction * stop_distance * reward_risk_ratio


def trailing_stop_series(close: pd.Series, atr: pd.Series, direction: int, multiplier: float = 2.5) -> pd.Series:
    """Chandelier-style trailing stop: trails the running extreme by
    `multiplier` x ATR, only ever moving in the trade's favor."""
    if direction == 1:
        running_extreme = close.cummax()
        stop = running_extreme - multiplier * atr
        return stop.cummax()
    running_extreme = close.cummin()
    stop = running_extreme + multiplier * atr
    return stop.cummin()


def is_stopped_out(direction: int, current_price: float, stop_price: float) -> bool:
    return current_price <= stop_price if direction == 1 else current_price >= stop_price
