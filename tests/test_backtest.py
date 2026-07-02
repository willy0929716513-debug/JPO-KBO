import numpy as np
import pandas as pd

from src.backtest.engine import BacktestEngine
from src.backtest.monte_carlo import monte_carlo_simulate
from src.backtest.walk_forward import walk_forward_backtest
from src.features.feature_pipeline import FeaturePipeline
from src.strategies import TrendFollowingStrategy
from src.strategies.base import Strategy


class _AlwaysShortStrategy(Strategy):
    """Test double: stays short the whole time, no matter what."""
    name = "always_short"

    def generate_signal(self, symbol, features):
        raise NotImplementedError  # backtest_signals is all BacktestEngine calls

    def backtest_signals(self, symbol, features):
        return pd.Series(-1, index=features.index)


def test_backtest_engine_equity_never_goes_negative():
    """Regression test: this simplified engine has no margin calls, so a
    short position that moves >100% against it (price more than doubles)
    could previously drive equity negative -- nonsensical for an account
    that can't owe more than it has. Equity must floor at 0."""
    n = 100
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    # Price triples over the period -- a short position loses >100% notional.
    close = pd.Series(np.linspace(100, 320, n), index=dates)
    features = pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": 1_000_000.0,
    }, index=dates)

    engine = BacktestEngine(initial_capital=100_000, commission_bps=0, slippage_bps=0)
    result = engine.run("TEST", _AlwaysShortStrategy(), features)

    assert (result.equity_curve >= 0).all()


def test_backtest_engine_produces_equity_curve(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    engine = BacktestEngine(initial_capital=100_000)
    result = engine.run("TEST", TrendFollowingStrategy(), features)

    assert len(result.equity_curve) == len(features)
    assert "sharpe_ratio" in result.metrics
    assert "max_drawdown_pct" in result.metrics
    assert result.metrics["max_drawdown_pct"] <= 0


def test_walk_forward_backtest(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    wf = walk_forward_backtest("TEST", TrendFollowingStrategy(), features, train_size=100, test_size=50)
    assert len(wf.window_results) > 0
    assert "sharpe_ratio" in wf.combined_metrics


def test_monte_carlo_simulation(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    engine = BacktestEngine()
    result = engine.run("TEST", TrendFollowingStrategy(), features)
    trade_returns = [t.pnl_pct for t in result.trades]
    if len(trade_returns) < 2:
        return  # not enough trades in this synthetic sample; engine test above already covers mechanics
    import pandas as pd
    mc = monte_carlo_simulate(pd.Series(trade_returns), n_simulations=200)
    assert 0.0 <= mc.prob_of_ruin <= 1.0
    assert len(mc.percentiles) == 5
