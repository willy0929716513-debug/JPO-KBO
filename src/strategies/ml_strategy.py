"""Wraps a trained VotingEnsemble as a Strategy: BUY when predicted
up-probability is high, SELL when predicted down-probability is high."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategies.base import Action, Signal, Strategy


class MLStrategy(Strategy):
    name = "ml_ensemble"

    def __init__(self, model, feature_cols: list[str], buy_threshold: float = 0.6, sell_threshold: float = 0.4):
        self.model = model
        self.feature_cols = feature_cols
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def _probabilities(self, features: pd.DataFrame) -> pd.Series:
        cols = [c for c in self.feature_cols if c in features.columns]
        X = features[cols].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
        proba = self.model.predict_proba(X)[:, 1]
        return pd.Series(proba, index=features.index)

    def generate_signal(self, symbol: str, features: pd.DataFrame) -> Signal:
        if len(features) < 60:
            return Signal(symbol, self.name, Action.HOLD, 0.0, float(features["close"].iloc[-1]) if len(features) else 0.0)

        price = float(features["close"].iloc[-1])
        atr_val = float(features.get("atr_14", pd.Series([0])).iloc[-1] or 0)
        prob_up = float(self._probabilities(features.tail(1)).iloc[-1])

        if prob_up >= self.buy_threshold:
            action = Action.BUY
            reasons = [f"ML ensemble P(up)={prob_up:.2%} >= {self.buy_threshold:.0%} threshold"]
            stop, target = price - atr_val * 2, price + atr_val * 4
        elif prob_up <= self.sell_threshold:
            action = Action.SELL
            reasons = [f"ML ensemble P(up)={prob_up:.2%} <= {self.sell_threshold:.0%} threshold"]
            stop, target = price + atr_val * 2, price - atr_val * 4
        else:
            action, reasons, stop, target = Action.HOLD, [f"ML ensemble P(up)={prob_up:.2%} (no strong edge)"], None, None

        confidence = abs(prob_up - 0.5) * 2
        return Signal(symbol, self.name, action, confidence, price, stop, target, reasons)
