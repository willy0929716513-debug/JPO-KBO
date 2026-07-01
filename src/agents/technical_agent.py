"""Wraps the rule-based strategy ensemble + regime detector into a single
agent opinion -- the same signal the dashboard shows, reframed as one voice
in the multi-agent decision process."""
from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentOpinion
from src.regime import RegimeDetector
from src.strategies import (
    BreakoutStrategy, MeanReversionStrategy, MomentumStrategy, StrategyCombiner, TrendFollowingStrategy,
)


class TechnicalAgent(Agent):
    name = "technical_agent"

    def __init__(self, combiner: StrategyCombiner | None = None, regime_detector: RegimeDetector | None = None):
        self.combiner = combiner or StrategyCombiner(
            [TrendFollowingStrategy(), MeanReversionStrategy(), BreakoutStrategy(), MomentumStrategy()]
        )
        self.regime_detector = regime_detector or RegimeDetector()

    def analyze(self, context: AgentContext) -> AgentOpinion:
        if len(context.features) < 60:
            return AgentOpinion(self.name, 0.0, 0.0, reasons=["Not enough history for technical analysis"])

        regime_state = self.regime_detector.detect(context.features)
        combined = self.combiner.combine(context.symbol, context.features, regime_state)
        lean = {"BUY": 1, "SELL": -1, "HOLD": 0}[combined.final_action.value] * combined.confidence
        reasons = [f"Regime={regime_state.regime.value}", f"Combined strategy action={combined.final_action.value}"]
        return AgentOpinion(self.name, lean, combined.confidence, reasons=reasons)
