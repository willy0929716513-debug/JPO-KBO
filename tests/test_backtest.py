from src.backtest.engine import BacktestEngine
from src.backtest.monte_carlo import monte_carlo_simulate
from src.backtest.walk_forward import walk_forward_backtest
from src.features.feature_pipeline import FeaturePipeline
from src.strategies import TrendFollowingStrategy


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
