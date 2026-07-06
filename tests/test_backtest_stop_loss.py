"""Regression tests for BacktestEngine actually enforcing a strategy's
stop_target_at() instead of only ever exiting when the raw signal flips
(the "建議停損/停利 was purely decorative" bug found during a full
system audit -- see mean_reversion's previously-catastrophic backtest
numbers, which were an artifact of never cutting a loser short).
"""
import numpy as np
import pandas as pd

from src.backtest.engine import BacktestEngine
from src.strategies.base import Action, Signal, Strategy


class _EnterOnceLong(Strategy):
    """Enters long on bar 0 and never signals again -- position is carried
    forward by the engine's stop-and-reverse logic until either a stop/target
    triggers or the backtest ends."""
    name = "enter_once_long"

    def __init__(self, stop_loss=None, take_profit=None):
        self._stop_loss = stop_loss
        self._take_profit = take_profit

    def generate_signal(self, symbol, features):
        raise NotImplementedError

    def backtest_signals(self, symbol, features):
        actions = pd.Series(0, index=features.index)
        actions.iloc[0] = 1
        return actions

    def stop_target_at(self, features, idx, direction):
        return self._stop_loss, self._take_profit


def _flat_features(prices, highs=None, lows=None):
    n = len(prices)
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    close = pd.Series(prices, index=dates, dtype=float)
    high = pd.Series(highs, index=dates, dtype=float) if highs is not None else close
    low = pd.Series(lows, index=dates, dtype=float) if lows is not None else close
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1_000_000.0}, index=dates)


def test_stop_loss_forces_exit_instead_of_riding_the_loss_to_the_end():
    # Enter long at 100, price grinds down to 50 -- without stop-loss
    # enforcement this would ride the entire way down (as it used to).
    prices = np.linspace(100, 50, 30)
    features = _flat_features(prices)

    engine = BacktestEngine(initial_capital=100_000, commission_bps=0, slippage_bps=0)
    strategy = _EnterOnceLong(stop_loss=90.0, take_profit=None)
    result = engine.run("TEST", strategy, features)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_price == 90.0  # exited exactly at the stop, not at the final bar's ~50
    assert trade.pnl_pct < 0
    assert trade.pnl_pct > -0.15  # loss capped near the ~10% stop distance, not the ~50% full slide


def test_take_profit_forces_exit_instead_of_giving_back_the_gain():
    # Enter long at 100, price rallies to 130 then fully round-trips back to 100.
    prices = np.concatenate([np.linspace(100, 130, 15), np.linspace(130, 100, 15)])
    features = _flat_features(prices)

    engine = BacktestEngine(initial_capital=100_000, commission_bps=0, slippage_bps=0)
    strategy = _EnterOnceLong(stop_loss=None, take_profit=120.0)
    result = engine.run("TEST", strategy, features)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_price == 120.0  # exited at the target on the way up, not given back on the round-trip
    assert trade.pnl_pct > 0.15


def test_no_stop_target_preserves_ride_until_signal_flip_behavior():
    # A strategy that never returns a stop/target should behave exactly like
    # before this change: the position rides all the way to the last bar.
    prices = np.linspace(100, 50, 30)
    features = _flat_features(prices)

    engine = BacktestEngine(initial_capital=100_000, commission_bps=0, slippage_bps=0)
    strategy = _EnterOnceLong(stop_loss=None, take_profit=None)
    result = engine.run("TEST", strategy, features)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_price == prices[-1]
    assert trade.pnl_pct < -0.3  # rode the full ~50% adverse move, unlike the stopped-out case above
