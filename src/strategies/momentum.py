from __future__ import annotations

import pandas as pd

from src.strategies.base import Action, Signal, Strategy


class MomentumStrategy(Strategy):
    """MACD histogram turning positive/negative + positive rate-of-change."""

    name = "momentum"

    def _raw_actions(self, features: pd.DataFrame) -> pd.Series:
        hist = features.get("macd_hist", pd.Series(dtype=float))
        hist_prev = hist.shift(1)
        roc = features.get("roc_10", pd.Series(dtype=float))

        buy = (hist > 0) & (hist_prev <= 0) & (roc > 0)
        sell = (hist < 0) & (hist_prev >= 0) & (roc < 0)
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
        roc_val = float(row.get("roc_10", 0) or 0)

        if action_val == 1:
            action = Action.BUY
            reasons = ["MACD histogram crossed above zero", f"10-bar ROC={roc_val:.2f}% (positive momentum)"]
            confidence = min(0.5 + abs(roc_val) / 50, 0.85)
            stop, target = price - atr_val * 2, price + atr_val * 3
        elif action_val == -1:
            action = Action.SELL
            reasons = ["MACD histogram crossed below zero", f"10-bar ROC={roc_val:.2f}% (negative momentum)"]
            confidence = min(0.5 + abs(roc_val) / 50, 0.85)
            stop, target = price + atr_val * 2, price - atr_val * 3
        else:
            action, reasons, confidence, stop, target = Action.HOLD, ["No fresh momentum crossover"], 0.3, None, None

        return Signal(symbol, self.name, action, confidence, price, stop, target, reasons)
