from __future__ import annotations

import pandas as pd

from src.strategies.base import Action, Signal, Strategy


class BreakoutStrategy(Strategy):
    """Donchian channel breakout confirmed by above-average volume."""

    name = "breakout"

    def __init__(self, volume_confirm_ratio: float = 1.3):
        self.volume_confirm_ratio = volume_confirm_ratio

    def _raw_actions(self, features: pd.DataFrame) -> pd.Series:
        close = features.get("close", pd.Series(dtype=float))
        dc_upper = features.get("dc_upper", pd.Series(dtype=float)).shift(1)
        dc_lower = features.get("dc_lower", pd.Series(dtype=float)).shift(1)
        vol_ratio = features.get("volume_ratio", pd.Series(dtype=float))

        buy = (close > dc_upper) & (vol_ratio >= self.volume_confirm_ratio)
        sell = (close < dc_lower) & (vol_ratio >= self.volume_confirm_ratio)
        actions = pd.Series(0, index=features.index)
        actions[buy] = 1
        actions[sell] = -1
        return actions

    def backtest_signals(self, symbol: str, features: pd.DataFrame) -> pd.Series:
        return self._raw_actions(features)

    def generate_signal(self, symbol: str, features: pd.DataFrame) -> Signal:
        if len(features) < 60:
            return Signal(symbol, self.name, Action.HOLD, 0.0, float(features["close"].iloc[-1]) if len(features) else 0.0)

        row = features.iloc[-1]
        action_val = int(self._raw_actions(features).iloc[-1])
        price = float(row["close"])
        atr_val = float(row.get("atr_14", 0) or 0)
        vol_ratio = float(row.get("volume_ratio", 1) or 1)

        if action_val == 1:
            action = Action.BUY
            reasons = ["Close broke above 20-bar Donchian upper channel", f"Volume ratio {vol_ratio:.2f}x average (confirmed)"]
            confidence = min(0.55 + (vol_ratio - self.volume_confirm_ratio) / 10, 0.9)
            stop, target = price - atr_val * 2, price + atr_val * 4
        elif action_val == -1:
            action = Action.SELL
            reasons = ["Close broke below 20-bar Donchian lower channel", f"Volume ratio {vol_ratio:.2f}x average (confirmed)"]
            confidence = min(0.55 + (vol_ratio - self.volume_confirm_ratio) / 10, 0.9)
            stop, target = price + atr_val * 2, price - atr_val * 4
        else:
            action, reasons, confidence, stop, target = Action.HOLD, ["No confirmed channel breakout"], 0.3, None, None

        return Signal(symbol, self.name, action, confidence, price, stop, target, reasons)
