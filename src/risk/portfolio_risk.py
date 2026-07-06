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


def check_correlation_limit(returns: dict[str, pd.Series], max_avg_correlation: float = 0.7) -> dict:
    """Flags whether the portfolio's average pairwise correlation exceeds a
    limit -- a portfolio of 10 "different" assets that are all 0.9
    correlated behaves like 1 asset with 10x the position size."""
    corr = correlation_matrix(returns)
    if corr.shape[0] < 2:
        return {"breached": False, "avg_correlation": 0.0}
    off_diag = corr.to_numpy()[~np.eye(corr.shape[0], dtype=bool)]
    avg_corr = float(np.nanmean(off_diag)) if len(off_diag) else 0.0
    return {"breached": avg_corr > max_avg_correlation, "avg_correlation": round(avg_corr, 3)}


def check_exposure_limits(weights: dict[str, float], group_of: dict[str, str],
                           max_group_weight: float = 0.4) -> dict:
    """Generic grouped exposure check, reusable for sector limits, country
    limits, or asset-class limits -- pass whichever `group_of` mapping
    (symbol -> group name) matches the limit you're enforcing."""
    totals: dict[str, float] = {}
    for symbol, weight in weights.items():
        group = group_of.get(symbol, "other")
        totals[group] = totals.get(group, 0.0) + weight
    breaches = {g: round(t, 4) for g, t in totals.items() if t > max_group_weight}
    return {"breached": bool(breaches), "breaches": breaches, "totals": {g: round(t, 4) for g, t in totals.items()}}


def portfolio_var(weights: dict[str, float], returns: dict[str, pd.Series], confidence: float = 0.95) -> float:
    """Historical-simulation VaR of the whole portfolio: combines each
    asset's return series into one portfolio return series via `weights`
    (correctly capturing diversification/correlation effects, unlike
    summing each asset's standalone VaR), then applies `historical_var`."""
    aligned = pd.DataFrame(returns).dropna()
    if aligned.empty:
        return 0.0
    w = pd.Series({s: weights.get(s, 0.0) for s in aligned.columns})
    portfolio_returns = aligned.mul(w, axis=1).sum(axis=1)
    return historical_var(portfolio_returns, confidence)


def portfolio_conditional_var(weights: dict[str, float], returns: dict[str, pd.Series],
                               confidence: float = 0.95) -> float:
    """Portfolio-level CVaR / Expected Shortfall, same combination approach as portfolio_var."""
    aligned = pd.DataFrame(returns).dropna()
    if aligned.empty:
        return 0.0
    w = pd.Series({s: weights.get(s, 0.0) for s in aligned.columns})
    portfolio_returns = aligned.mul(w, axis=1).sum(axis=1)
    return conditional_var(portfolio_returns, confidence)


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
    re-arming only after equity recovers above a smaller threshold.

    `initially_tripped` lets a caller restore whether this breaker was
    already tripped as of the last time it was checked -- without it, a
    fresh instance always starts untripped, which defeats the whole
    "stays halted until it recovers past reset_drawdown_pct" hysteresis
    the moment the caller doesn't keep the same object alive across calls
    (e.g. a new instance built on every pipeline run).
    """

    def __init__(self, max_drawdown_pct: float = 0.20, reset_drawdown_pct: float = 0.10,
                 initially_tripped: bool = False):
        self.max_drawdown_pct = max_drawdown_pct
        self.reset_drawdown_pct = reset_drawdown_pct
        self._tripped = initially_tripped

    def update(self, equity_curve: pd.Series) -> bool:
        """Returns True if trading should be halted."""
        dd = abs(max_drawdown(equity_curve))
        if dd >= self.max_drawdown_pct:
            self._tripped = True
        elif dd <= self.reset_drawdown_pct:
            self._tripped = False
        return self._tripped
