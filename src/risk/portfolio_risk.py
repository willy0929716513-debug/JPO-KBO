"""Portfolio-level risk controls: correlation risk, Value-at-Risk / CVaR,
maximum-drawdown circuit breaker, and risk-of-ruin estimation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def correlation_matrix(returns: dict[str, pd.Series]) -> pd.DataFrame:
    return pd.DataFrame(returns).corr()


def portfolio_diversification_score(returns: dict[str, pd.Series]) -> float:
    """1.0 = fully diversified (zero avg correlation), 0.0 = fully correlated."""
    corr = correlation_matrix(returns)
    if corr.shape[0] < 2:
        return 1.0
    off_diag = corr.to_numpy()[~np.eye(corr.shape[0], dtype=bool)]
    avg_corr = float(np.nanmean(np.abs(off_diag)))
    return round(1 - avg_corr, 3)


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Historical-simulation VaR: the loss threshold not exceeded with
    `confidence` probability over one period. Returned as a positive number
    (fraction of capital)."""
    if returns.empty:
        return 0.0
    return float(-np.percentile(returns.dropna(), (1 - confidence) * 100))


def conditional_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """CVaR / Expected Shortfall: average loss in the worst (1-confidence) tail."""
    if returns.empty:
        return 0.0
    var = -historical_var(returns, confidence)
    tail = returns[returns <= var]
    if tail.empty:
        return abs(var)
    return float(-tail.mean())


def max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    return float(drawdown.min())


def risk_of_ruin(win_rate: float, win_loss_ratio: float, risk_per_trade: float, capital_units: int = 20) -> float:
    """Simplified risk-of-ruin approximation (classic gambler's-ruin style
    formula) -- probability of losing `capital_units` consecutive risk units."""
    if win_rate <= 0 or win_rate >= 1:
        return 1.0 if win_rate <= 0 else 0.0
    edge = win_rate * win_loss_ratio - (1 - win_rate)
    if edge <= 0:
        return 1.0
    q_over_p = ((1 - win_rate) / win_rate) ** capital_units
    return float(np.clip(q_over_p, 0.0, 1.0))


class DrawdownCircuitBreaker:
    """Halts new position entries once portfolio drawdown breaches a limit,
    re-arming only after equity recovers above a smaller threshold."""

    def __init__(self, max_drawdown_pct: float = 0.20, reset_drawdown_pct: float = 0.10):
        self.max_drawdown_pct = max_drawdown_pct
        self.reset_drawdown_pct = reset_drawdown_pct
        self._tripped = False

    def update(self, equity_curve: pd.Series) -> bool:
        """Returns True if trading should be halted."""
        dd = abs(max_drawdown(equity_curve))
        if dd >= self.max_drawdown_pct:
            self._tripped = True
        elif dd <= self.reset_drawdown_pct:
            self._tripped = False
        return self._tripped
