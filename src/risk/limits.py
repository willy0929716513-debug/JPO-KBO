"""Daily / weekly / monthly loss-limit circuit breakers -- the standard
calendar-based risk control at prop desks and funds, distinct from
`DrawdownCircuitBreaker` (which tracks peak-to-trough drawdown regardless
of calendar time). Feed it a datetime-indexed equity curve; it reports
whether trading should be halted for breaching any configured window.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class LossLimitConfig:
    daily_loss_limit_pct: float = 0.03
    weekly_loss_limit_pct: float = 0.06
    monthly_loss_limit_pct: float = 0.12


@dataclass
class LossLimitStatus:
    halted: bool
    breached: list[str] = field(default_factory=list)
    daily_pnl_pct: float = 0.0
    weekly_pnl_pct: float = 0.0
    monthly_pnl_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "halted": self.halted, "breached": self.breached,
            "daily_pnl_pct": self.daily_pnl_pct, "weekly_pnl_pct": self.weekly_pnl_pct,
            "monthly_pnl_pct": self.monthly_pnl_pct,
        }


class LossLimitMonitor:
    def __init__(self, config: LossLimitConfig | None = None):
        self.config = config or LossLimitConfig()

    def check(self, equity_curve: pd.Series) -> LossLimitStatus:
        if len(equity_curve) < 2:
            return LossLimitStatus(halted=False)

        equity_curve = equity_curve.sort_index()
        last_equity = float(equity_curve.iloc[-1])
        last_date = equity_curve.index[-1]

        def pct_change_since(start_date) -> float:
            window = equity_curve[equity_curve.index >= start_date]
            if window.empty:
                return 0.0
            return float(last_equity / window.iloc[0] - 1)

        daily_pnl = pct_change_since(last_date - pd.Timedelta(days=1))
        weekly_pnl = pct_change_since(last_date - pd.Timedelta(days=7))
        monthly_pnl = pct_change_since(last_date - pd.Timedelta(days=30))

        breached = []
        if daily_pnl <= -self.config.daily_loss_limit_pct:
            breached.append("daily")
        if weekly_pnl <= -self.config.weekly_loss_limit_pct:
            breached.append("weekly")
        if monthly_pnl <= -self.config.monthly_loss_limit_pct:
            breached.append("monthly")

        return LossLimitStatus(
            halted=bool(breached), breached=breached,
            daily_pnl_pct=round(daily_pnl * 100, 2), weekly_pnl_pct=round(weekly_pnl * 100, 2),
            monthly_pnl_pct=round(monthly_pnl * 100, 2),
        )
