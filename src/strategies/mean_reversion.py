from __future__ import annotations

import pandas as pd

from src.strategies.base import Action, Signal, Strategy


class MeanReversionStrategy(Strategy):
    """RSI extremes + Bollinger Band touch, only taken in non-trending (range) conditions."""

    name = "mean_reversion"

    def __init__(self, rsi_oversold: float = 30.0, rsi_overbought: float = 70.0, adx_range_ceiling: float = 25.0):
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.adx_range_ceiling = adx_range_ceiling

    def _raw_actions(self, features: pd.DataFrame) -> pd.Series:
        rsi = features.get("rsi_14", pd.Series(dtype=float))
        close = features.get("close", pd.Series(dtype=float))
        bb_lower = features.get("bb_lower", pd.Series(dtype=float))
        bb_upper = features.get("bb_upper", pd.Series(dtype=float))
        ranging = features.get("adx", pd.Series(dtype=float)) < self.adx_range_ceiling

        buy = (rsi <= self.rsi_oversold) & (close <= bb_lower) & ranging
        sell = (rsi >= self.rsi_overbought) & (close >= bb_upper) & ranging
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
        rsi_val = float(row.get("rsi_14", 50) or 50)
        bb_mid = float(row.get("bb_mid", price) or price)
        atr_val = float(row.get("atr_14", 0) or 0)

        if action_val == 1:
            action = Action.BUY
            reasons = [f"RSI={rsi_val:.1f} <= {self.rsi_oversold} (oversold)", "Price at/below lower Bollinger Band",
                       "Market in range (low ADX)"]
            confidence = min(0.5 + (self.rsi_oversold - rsi_val) / 100, 0.9)
            stop, target = price - atr_val * 1.5, bb_mid
        elif action_val == -1:
            action = Action.SELL
            reasons = [f"RSI={rsi_val:.1f} >= {self.rsi_overbought} (overbought)", "Price at/above upper Bollinger Band",
                       "Market in range (low ADX)"]
            confidence = min(0.5 + (rsi_val - self.rsi_overbought) / 100, 0.9)
            stop, target = price + atr_val * 1.5, bb_mid
        else:
            action, reasons, confidence, stop, target = Action.HOLD, ["No mean-reversion extreme detected"], 0.3, None, None

        return Signal(symbol, self.name, action, confidence, price, stop, target, reasons)
