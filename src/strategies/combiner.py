"""Combines signals from multiple strategies into one final recommendation,
weighting each strategy by how well-suited it is to the detected market
regime (e.g. trend-following gets more weight in a trending regime,
mean-reversion gets more weight in a ranging regime).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.regime import MarketRegime, RegimeState
from src.strategies.base import Action, Signal, Strategy

# strategy_name -> weight multiplier per regime (1.0 = neutral)
_REGIME_WEIGHTS: dict[MarketRegime, dict[str, float]] = {
    MarketRegime.BULL_TREND: {"trend_following": 1.5, "momentum": 1.3, "breakout": 1.2, "mean_reversion": 0.3, "ml_ensemble": 1.0},
    MarketRegime.BEAR_TREND: {"trend_following": 1.5, "momentum": 1.3, "breakout": 1.2, "mean_reversion": 0.3, "ml_ensemble": 1.0},
    MarketRegime.RANGE_BOUND: {"trend_following": 0.4, "momentum": 0.6, "breakout": 0.5, "mean_reversion": 1.6, "ml_ensemble": 1.0},
    MarketRegime.HIGH_VOLATILITY: {"trend_following": 0.6, "momentum": 0.6, "breakout": 0.7, "mean_reversion": 0.5, "ml_ensemble": 0.8},
    MarketRegime.LOW_VOLATILITY: {"trend_following": 1.0, "momentum": 0.8, "breakout": 0.8, "mean_reversion": 1.2, "ml_ensemble": 1.0},
    MarketRegime.UNKNOWN: {"trend_following": 1.0, "momentum": 1.0, "breakout": 1.0, "mean_reversion": 1.0, "ml_ensemble": 1.0},
}


@dataclass
class CombinedSignal:
    symbol: str
    final_action: Action
    confidence: float
    price: float
    stop_loss: float | None
    take_profit: float | None
    regime: str
    votes: list[dict]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "final_action": self.final_action.value,
            "confidence": round(self.confidence, 3),
            "price": round(self.price, 6) if self.price else None,
            "stop_loss": round(self.stop_loss, 6) if self.stop_loss else None,
            "take_profit": round(self.take_profit, 6) if self.take_profit else None,
            "regime": self.regime,
            "votes": self.votes,
        }


class StrategyCombiner:
    def __init__(self, strategies: list[Strategy]):
        self.strategies = strategies

    def combine(self, symbol: str, features: pd.DataFrame, regime_state: RegimeState) -> CombinedSignal:
        weights = _REGIME_WEIGHTS.get(regime_state.regime, _REGIME_WEIGHTS[MarketRegime.UNKNOWN])
        signals: list[Signal] = [s.generate_signal(symbol, features) for s in self.strategies]

        score = 0.0
        total_weight = 0.0
        votes = []
        stops, targets = [], []
        for sig in signals:
            w = weights.get(sig.strategy, 1.0)
            direction = {"BUY": 1, "SELL": -1, "HOLD": 0}[sig.action.value]
            score += direction * sig.confidence * w
            total_weight += w
            votes.append({**sig.to_dict(), "weight": round(w, 2)})
            if sig.action != Action.HOLD:
                if sig.stop_loss:
                    stops.append(sig.stop_loss)
                if sig.take_profit:
                    targets.append(sig.take_profit)

        normalized_score = score / total_weight if total_weight else 0.0
        price = float(features["close"].iloc[-1]) if len(features) else 0.0

        if normalized_score >= 0.15:
            final_action = Action.BUY
        elif normalized_score <= -0.15:
            final_action = Action.SELL
        else:
            final_action = Action.HOLD

        stop_loss = (sum(s for s in stops if (s < price) == (final_action == Action.BUY)) / len([s for s in stops if (s < price) == (final_action == Action.BUY)])
                     if final_action != Action.HOLD and stops else None)
        take_profit = (sum(t for t in targets if (t > price) == (final_action == Action.BUY)) / len([t for t in targets if (t > price) == (final_action == Action.BUY)])
                       if final_action != Action.HOLD and targets else None)

        return CombinedSignal(
            symbol=symbol, final_action=final_action, confidence=round(min(abs(normalized_score), 1.0), 3),
            price=price, stop_loss=stop_loss, take_profit=take_profit,
            regime=regime_state.regime.value, votes=votes,
        )
