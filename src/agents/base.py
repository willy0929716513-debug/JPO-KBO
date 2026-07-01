"""Base interface every agent implements: given a shared AgentContext,
produce an AgentOpinion (directional lean + confidence + reasoning). The
DecisionEngine aggregates opinions from every registered agent into one
final call -- similar in spirit to how a real trading desk combines input
from research, risk, and portfolio management before executing.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class AgentContext:
    """Shared inputs every agent may draw on. Not every agent uses every field --
    an agent should degrade gracefully (return a neutral, low-confidence
    opinion) when a field it needs is missing rather than raise."""
    symbol: str
    features: pd.DataFrame
    macro_snapshot: dict | None = None
    sentiment_snapshot: dict | None = None
    equity_curve: pd.Series | None = None
    portfolio_weights: dict[str, float] | None = None
    asset_class_of: dict[str, str] | None = None
    returns_by_symbol: dict[str, pd.Series] | None = None


@dataclass
class AgentOpinion:
    agent_name: str
    lean: float             # -1 (bearish) .. +1 (bullish)
    confidence: float        # 0..1
    veto: bool = False       # True forces a HOLD regardless of every other agent (used by RiskAgent/PortfolioAgent)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"agent": self.agent_name, "lean": round(self.lean, 3), "confidence": round(self.confidence, 3),
                "veto": self.veto, "reasons": self.reasons}


class Agent(ABC):
    name: str = "base_agent"

    @abstractmethod
    def analyze(self, context: AgentContext) -> AgentOpinion:
        raise NotImplementedError
