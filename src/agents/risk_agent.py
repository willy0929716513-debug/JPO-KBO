"""Evaluates portfolio-level risk limits and can veto a trade outright
regardless of how bullish/bearish every other agent is. Risk management
overriding conviction is the single most important rule at any real
trading desk -- this agent is what enforces that in the decision engine.
"""
from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentOpinion
from src.risk import DrawdownCircuitBreaker, LossLimitMonitor, check_correlation_limit


class RiskAgent(Agent):
    name = "risk_agent"

    def __init__(self, drawdown_breaker: DrawdownCircuitBreaker | None = None,
                 loss_limit_monitor: LossLimitMonitor | None = None, max_avg_correlation: float = 0.85):
        self.drawdown_breaker = drawdown_breaker or DrawdownCircuitBreaker()
        self.loss_limit_monitor = loss_limit_monitor or LossLimitMonitor()
        self.max_avg_correlation = max_avg_correlation

    def analyze(self, context: AgentContext) -> AgentOpinion:
        reasons: list[str] = []
        veto = False

        if context.equity_curve is not None and len(context.equity_curve) > 1:
            if self.drawdown_breaker.update(context.equity_curve):
                veto = True
                reasons.append("Max drawdown circuit breaker tripped -- new entries halted")

            loss_status = self.loss_limit_monitor.check(context.equity_curve)
            if loss_status.halted:
                veto = True
                reasons.append(
                    f"Loss limit breached: {', '.join(loss_status.breached)} "
                    f"(daily={loss_status.daily_pnl_pct}%, weekly={loss_status.weekly_pnl_pct}%, "
                    f"monthly={loss_status.monthly_pnl_pct}%)"
                )

        if context.returns_by_symbol is not None and len(context.returns_by_symbol) > 1:
            corr_check = check_correlation_limit(context.returns_by_symbol, self.max_avg_correlation)
            if corr_check["breached"]:
                # Flagged but not a hard veto -- concentration risk warrants smaller size, not necessarily a full stop.
                reasons.append(
                    f"Portfolio average correlation {corr_check['avg_correlation']} exceeds "
                    f"{self.max_avg_correlation} -- consider reducing position size"
                )

        if not reasons:
            reasons.append("No risk limits breached")

        return AgentOpinion(self.name, 0.0, 1.0 if veto else 0.0, veto=veto, reasons=reasons)
