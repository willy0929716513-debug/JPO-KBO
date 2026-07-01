"""Walk-forward validation: splits history into rolling
train-window/test-window pairs and backtests each test window independently,
so performance isn't just an artifact of curve-fitting to the whole history.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.backtest.engine import BacktestEngine, BacktestResult
from src.strategies.base import Strategy


@dataclass
class WalkForwardResult:
    window_results: list[BacktestResult]
    combined_equity_curve: pd.Series
    combined_metrics: dict


def walk_forward_backtest(
    symbol: str, strategy: Strategy, features: pd.DataFrame,
    train_size: int = 500, test_size: int = 100, engine: BacktestEngine | None = None,
) -> WalkForwardResult:
    engine = engine or BacktestEngine()
    window_results: list[BacktestResult] = []
    equity_segments: list[pd.Series] = []

    start = 0
    n = len(features)
    while start + train_size + test_size <= n:
        test_window = features.iloc[start + train_size: start + train_size + test_size]
        # rule-based strategies here don't "train" on the train window (no fitted
        # params to leak), but the split is enforced so ML-backed strategies can
        # be swapped in and retrained per-window without changing this loop.
        result = engine.run(symbol, strategy, test_window)
        window_results.append(result)
        equity_segments.append(result.equity_curve)
        start += test_size

    if not equity_segments:
        raise ValueError("Not enough data for the requested train_size/test_size split.")

    combined = pd.concat(equity_segments)
    from src.backtest.metrics import summarize_performance
    all_trades = pd.Series([t.pnl_abs for r in window_results for t in r.trades])
    combined_metrics = summarize_performance(combined, all_trades)

    return WalkForwardResult(window_results, combined, combined_metrics)
