"""Vectorized-ish backtest engine: turns a strategy's BUY/SELL/HOLD signal
series into a stop-and-reverse position series, applies commission +
slippage on every position change, and produces an equity curve + trade log.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.backtest.metrics import summarize_performance
from src.strategies.base import Strategy


@dataclass
class Trade:
    entry_time: str
    exit_time: str
    direction: int  # 1 long, -1 short
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_abs: float


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade]
    metrics: dict
    position_series: pd.Series

    def trades_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([t.__dict__ for t in self.trades])


class BacktestEngine:
    def __init__(self, initial_capital: float = 100_000.0, commission_bps: float = 5.0,
                 slippage_bps: float = 5.0, risk_free_rate: float = 0.04, periods_per_year: int = 252):
        self.initial_capital = initial_capital
        self.cost_bps = (commission_bps + slippage_bps) / 10_000
        self.risk_free_rate = risk_free_rate
        self.periods_per_year = periods_per_year

    def run(self, symbol: str, strategy: Strategy, features: pd.DataFrame) -> BacktestResult:
        actions = strategy.backtest_signals(symbol, features).reindex(features.index).fillna(0)
        close = features["close"]

        position = 0
        entry_price = 0.0
        entry_time = None
        equity = self.initial_capital
        equity_curve = []
        trades: list[Trade] = []

        for i, (ts, price) in enumerate(close.items()):
            action = int(actions.iloc[i])
            desired_position = action if action != 0 else position

            if desired_position != position:
                if position != 0:
                    pnl_pct = position * (price / entry_price - 1) - self.cost_bps
                    pnl_abs = equity * pnl_pct
                    equity += pnl_abs
                    trades.append(Trade(str(entry_time), str(ts), position, entry_price, price, pnl_pct, pnl_abs))
                if desired_position != 0:
                    equity -= equity * self.cost_bps  # entry cost
                    entry_price = price
                    entry_time = ts
                position = desired_position

            # mark-to-market unrealized PnL for the equity curve
            if position != 0 and entry_price:
                unrealized = position * (price / entry_price - 1)
                equity_curve.append(equity * (1 + unrealized))
            else:
                equity_curve.append(equity)

        # close any open position at the final bar
        if position != 0:
            price = close.iloc[-1]
            pnl_pct = position * (price / entry_price - 1) - self.cost_bps
            pnl_abs = equity * pnl_pct
            equity += pnl_abs
            trades.append(Trade(str(entry_time), str(close.index[-1]), position, entry_price, price, pnl_pct, pnl_abs))
            equity_curve[-1] = equity

        equity_series = pd.Series(equity_curve, index=close.index, name="equity")
        trade_pnls = pd.Series([t.pnl_abs for t in trades])
        metrics = summarize_performance(equity_series, trade_pnls, self.risk_free_rate, self.periods_per_year)

        return BacktestResult(
            equity_curve=equity_series, trades=trades, metrics=metrics,
            position_series=actions,
        )
