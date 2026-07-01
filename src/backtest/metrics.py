"""Performance metrics computed from an equity curve / trade log."""
from __future__ import annotations

import numpy as np
import pandas as pd


def cagr(equity_curve: pd.Series, periods_per_year: int = 252) -> float:
    if len(equity_curve) < 2 or equity_curve.iloc[0] <= 0:
        return 0.0
    n_years = len(equity_curve) / periods_per_year
    if n_years <= 0:
        return 0.0
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0]
    if total_return <= 0:
        return -1.0
    return float(total_return ** (1 / n_years) - 1)


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.04, periods_per_year: int = 252) -> float:
    excess = returns - risk_free_rate / periods_per_year
    std = excess.std()
    # A near-zero std (e.g. a flat, all-cash equity curve with no trades) makes
    # this ratio blow up to a meaningless huge number from floating-point noise
    # rather than a true division by exactly zero -- guard with an epsilon.
    if np.isnan(std) or std < 1e-8:
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.04, periods_per_year: int = 252) -> float:
    excess = returns - risk_free_rate / periods_per_year
    downside = excess[excess < 0]
    downside_std = downside.std()
    if np.isnan(downside_std) or downside_std < 1e-8:
        return 0.0
    return float(excess.mean() / downside_std * np.sqrt(periods_per_year))


def calmar_ratio(equity_curve: pd.Series, periods_per_year: int = 252) -> float:
    from src.risk.portfolio_risk import max_drawdown
    mdd = abs(max_drawdown(equity_curve))
    if mdd < 1e-8:
        return 0.0
    return float(cagr(equity_curve, periods_per_year) / mdd)


def win_rate(trade_pnls: pd.Series) -> float:
    if trade_pnls.empty:
        return 0.0
    return float((trade_pnls > 0).mean())


def profit_factor(trade_pnls: pd.Series) -> float:
    gains = trade_pnls[trade_pnls > 0].sum()
    losses = -trade_pnls[trade_pnls < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def summarize_performance(equity_curve: pd.Series, trade_pnls: pd.Series, risk_free_rate: float = 0.04,
                           periods_per_year: int = 252) -> dict:
    from src.risk.portfolio_risk import max_drawdown

    returns = equity_curve.pct_change().dropna()
    return {
        "total_return_pct": round((equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100, 2) if len(equity_curve) > 1 else 0.0,
        "cagr_pct": round(cagr(equity_curve, periods_per_year) * 100, 2),
        "sharpe_ratio": round(sharpe_ratio(returns, risk_free_rate, periods_per_year), 3),
        "sortino_ratio": round(sortino_ratio(returns, risk_free_rate, periods_per_year), 3),
        "calmar_ratio": round(calmar_ratio(equity_curve, periods_per_year), 3),
        "max_drawdown_pct": round(max_drawdown(equity_curve) * 100, 2),
        "win_rate_pct": round(win_rate(trade_pnls) * 100, 2),
        "profit_factor": round(profit_factor(trade_pnls), 3) if np.isfinite(profit_factor(trade_pnls)) else None,
        "num_trades": int(len(trade_pnls)),
    }
