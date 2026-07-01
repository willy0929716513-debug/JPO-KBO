"""Aggregates every registered agent's opinion into one final BUY/SELL/HOLD
decision. Any opinion with veto=True forces HOLD outright (risk management
overrides conviction); otherwise the final call is a confidence-weighted
average of every agent's directional lean.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.agents.base import Agent, AgentContext, AgentOpinion
from src.strategies.base import Action


@dataclass
class Decision:
    symbol: str
    action: Action
    confidence: float
    vetoed: bool
    opinions: list[AgentOpinion] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "action": self.action.value, "confidence": round(self.confidence, 3),
            "vetoed": self.vetoed, "opinions": [o.to_dict() for o in self.opinions],
        }


class DecisionEngine:
    def __init__(self, agents: list[Agent], buy_threshold: float = 0.15, sell_threshold: float = -0.15):
        self.agents = agents
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def decide(self, context: AgentContext) -> Decision:
        opinions = [agent.analyze(context) for agent in self.agents]

        if any(o.veto for o in opinions):
            return Decision(context.symbol, Action.HOLD, 0.0, True, opinions)

        total_weight = sum(o.confidence for o in opinions if o.confidence > 0)
        score = sum(o.lean * o.confidence for o in opinions) / total_weight if total_weight > 0 else 0.0

        if score >= self.buy_threshold:
            action = Action.BUY
        elif score <= self.sell_threshold:
            action = Action.SELL
        else:
            action = Action.HOLD

        return Decision(context.symbol, action, round(min(abs(score), 1.0), 3), False, opinions)
