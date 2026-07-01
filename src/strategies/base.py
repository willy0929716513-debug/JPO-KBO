"""Common Signal type and Strategy interface shared by every strategy."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    symbol: str
    strategy: str
    action: Action
    confidence: float          # 0-1
    price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    reasons: list[str] = field(default_factory=list)
    timestamp: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "action": self.action.value,
            "confidence": round(self.confidence, 3),
            "price": round(self.price, 6) if self.price else None,
            "stop_loss": round(self.stop_loss, 6) if self.stop_loss else None,
            "take_profit": round(self.take_profit, 6) if self.take_profit else None,
            "reasons": self.reasons,
            "timestamp": self.timestamp,
        }


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def generate_signal(self, symbol: str, features: pd.DataFrame) -> Signal:
        """Given a feature matrix (index=time, columns=OHLCV+indicators),
        return a Signal for the latest bar."""
        raise NotImplementedError

    def backtest_signals(self, symbol: str, features: pd.DataFrame) -> pd.Series:
        """Vectorized version used by the backtester: returns a Series of
        Action values (as ints: 1=BUY, -1=SELL, 0=HOLD) aligned to `features.index`.
        Default implementation just replays generate_signal bar-by-bar (slow but
        always correct); override for speed on large universes.
        """
        actions = []
        for i in range(len(features)):
            window = features.iloc[: i + 1]
            if len(window) < 60:
                actions.append(0)
                continue
            sig = self.generate_signal(symbol, window)
            actions.append({"BUY": 1, "SELL": -1, "HOLD": 0}[sig.action.value])
        return pd.Series(actions, index=features.index)
