"""Evaluates portfolio-construction constraints (asset-class exposure caps)
for a symbol -- vetoes new entries when adding to this symbol's asset class
would push it over the configured limit, so the decision engine never
concentrates the whole portfolio in one asset class just because that
class has the strongest technical signals right now."""
from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentOpinion


class PortfolioAgent(Agent):
    name = "portfolio_agent"

    def __init__(self, max_asset_class_weight: float = 0.5):
        self.max_asset_class_weight = max_asset_class_weight

    def analyze(self, context: AgentContext) -> AgentOpinion:
        if not context.portfolio_weights or not context.asset_class_of:
            return AgentOpinion(self.name, 0.0, 0.0,
                                 reasons=["No portfolio weights supplied -- skipping exposure check"])

        asset_class = context.asset_class_of.get(context.symbol, "other")
        class_total = sum(
            w for s, w in context.portfolio_weights.items()
            if context.asset_class_of.get(s, "other") == asset_class
        )

        if class_total > self.max_asset_class_weight:
            return AgentOpinion(
                self.name, 0.0, 0.5, veto=True,
                reasons=[f"Asset class '{asset_class}' already at {class_total:.1%} of portfolio "
                         f"(limit {self.max_asset_class_weight:.0%}) -- blocking new entries"],
            )
        return AgentOpinion(
            self.name, 0.0, 0.0,
            reasons=[f"Asset class '{asset_class}' at {class_total:.1%} of portfolio (within limit)"],
        )
