"""Monte Carlo simulation: resamples the trade-return sequence (with
replacement) many times to estimate the distribution of possible outcomes
and the probability of hitting a large drawdown -- a much more honest view
of risk than a single historical equity curve.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MonteCarloResult:
    final_equity_distribution: np.ndarray
    max_drawdown_distribution: np.ndarray
    prob_of_ruin: float  # probability final equity < 50% of starting capital
    percentiles: dict[str, float]


def monte_carlo_simulate(
    trade_returns_pct: pd.Series, initial_capital: float = 100_000.0,
    n_simulations: int = 2000, n_trades: int | None = None, seed: int = 42,
) -> MonteCarloResult:
    if trade_returns_pct.empty:
        raise ValueError("No trade returns to simulate from.")

    rng = np.random.default_rng(seed)
    n_trades = n_trades or len(trade_returns_pct)
    returns_arr = trade_returns_pct.to_numpy()

    final_equities = np.empty(n_simulations)
    max_drawdowns = np.empty(n_simulations)

    for i in range(n_simulations):
        sampled = rng.choice(returns_arr, size=n_trades, replace=True)
        equity_path = initial_capital * np.cumprod(1 + sampled)
        equity_path = np.insert(equity_path, 0, initial_capital)
        running_max = np.maximum.accumulate(equity_path)
        drawdown = equity_path / running_max - 1
        final_equities[i] = equity_path[-1]
        max_drawdowns[i] = drawdown.min()

    prob_of_ruin = float(np.mean(final_equities < initial_capital * 0.5))
    percentiles = {
        f"p{p}": float(np.percentile(final_equities, p)) for p in (5, 25, 50, 75, 95)
    }

    return MonteCarloResult(final_equities, max_drawdowns, prob_of_ruin, percentiles)
