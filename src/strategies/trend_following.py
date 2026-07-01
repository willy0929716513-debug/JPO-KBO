from __future__ import annotations

import pandas as pd

from src.strategies.base import Action, Signal, Strategy


class TrendFollowingStrategy(Strategy):
    """EMA(20/50) cross + ADX trend strength + SuperTrend direction agreement."""

    name = "trend_following"

    def __init__(self, adx_threshold: float = 20.0, atr_stop_mult: float = 2.0, atr_tp_mult: float = 4.0):
        self.adx_threshold = adx_threshold
        self.atr_stop_mult = atr_stop_mult
        self.atr_tp_mult = atr_tp_mult

    def _raw_actions(self, features: pd.DataFrame) -> pd.Series:
        ema_bull = features.get("ema_20", pd.Series(dtype=float)) > features.get("ema_50", pd.Series(dtype=float))
        strong_trend = features.get("adx", pd.Series(dtype=float)) >= self.adx_threshold
        st_bull = features.get("supertrend_dir", pd.Series(dtype=float)) == 1

        buy = ema_bull & strong_trend & st_bull
        sell = (~ema_bull) & strong_trend & (~st_bull)
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
        actions = self._raw_actions(features)
        action_val = int(actions.iloc[-1])
        price = float(row["close"])
        atr_val = float(row.get("atr_14", 0) or 0)
        adx_val = float(row.get("adx", 0) or 0)

        reasons = []
        confidence = min(0.5 + (adx_val - self.adx_threshold) / 100, 0.95) if action_val != 0 else 0.3

        if action_val == 1:
            action, reasons = Action.BUY, [
                f"EMA20 > EMA50 (uptrend)", f"ADX={adx_val:.1f} >= {self.adx_threshold} (strong trend)",
                "SuperTrend direction bullish",
            ]
            stop = price - atr_val * self.atr_stop_mult
            target = price + atr_val * self.atr_tp_mult
        elif action_val == -1:
            action, reasons = Action.SELL, [
                f"EMA20 < EMA50 (downtrend)", f"ADX={adx_val:.1f} >= {self.adx_threshold} (strong trend)",
                "SuperTrend direction bearish",
            ]
            stop = price + atr_val * self.atr_stop_mult
            target = price - atr_val * self.atr_tp_mult
        else:
            action, reasons, stop, target = Action.HOLD, ["No aligned trend signal (ranging or weak ADX)"], None, None

        return Signal(symbol, self.name, action, confidence, price, stop, target, reasons)
