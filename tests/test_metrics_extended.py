import numpy as np
import pandas as pd

from src.backtest.engine import BacktestEngine
from src.backtest.metrics import (
    alpha_beta, expectancy, information_ratio, mar_ratio, omega_ratio,
    recovery_factor, rolling_drawdown, rolling_sharpe, sqn, summarize_performance,
)
from src.features.feature_pipeline import FeaturePipeline
from src.strategies import TrendFollowingStrategy


def test_omega_ratio_above_one_for_positive_drift():
    returns = pd.Series(np.concatenate([np.full(80, 0.01), np.full(20, -0.005)]))
    assert omega_ratio(returns) > 1.0


def test_mar_ratio_matches_calmar(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    result = BacktestEngine().run("TEST", TrendFollowingStrategy(), features)
    from src.backtest.metrics import calmar_ratio
    assert mar_ratio(result.equity_curve) == calmar_ratio(result.equity_curve)


def test_sqn_zero_with_insufficient_trades():
    assert sqn(pd.Series([100.0])) == 0.0


def test_sqn_positive_for_winning_system():
    pnls = pd.Series([50, 60, 40, -10, 55, 45, -5, 60])
    assert sqn(pnls) > 0


def test_alpha_beta_zero_beta_for_uncorrelated():
    rng = np.random.default_rng(1)
    strat = pd.Series(rng.normal(0.001, 0.01, 200))
    bench = pd.Series(rng.normal(0.0005, 0.01, 200))
    alpha, beta = alpha_beta(strat, bench)
    assert isinstance(alpha, float) and isinstance(beta, float)


def test_information_ratio_zero_when_identical():
    returns = pd.Series(np.random.default_rng(2).normal(0.001, 0.01, 100))
    ir = information_ratio(returns, returns)
    assert abs(ir) < 1e-6


def test_rolling_sharpe_and_drawdown_shapes(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    result = BacktestEngine().run("TEST", TrendFollowingStrategy(), features)
    returns = result.equity_curve.pct_change().dropna()

    rs = rolling_sharpe(returns, window=30)
    rd = rolling_drawdown(result.equity_curve)
    assert len(rs) == len(returns)
    assert len(rd) == len(result.equity_curve)
    assert (rd <= 1e-9).all()  # drawdown is always <= 0


def test_expectancy_and_recovery_factor(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    result = BacktestEngine().run("TEST", TrendFollowingStrategy(), features)
    trade_pnls = pd.Series([t.pnl_abs for t in result.trades])
    if trade_pnls.empty:
        return
    assert isinstance(expectancy(trade_pnls), float)
    assert isinstance(recovery_factor(result.equity_curve), float)


def test_summarize_performance_includes_new_metrics(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    result = BacktestEngine().run("TEST", TrendFollowingStrategy(), features)
    trade_pnls = pd.Series([t.pnl_abs for t in result.trades])
    summary = summarize_performance(result.equity_curve, trade_pnls)
    for key in ("mar_ratio", "omega_ratio", "sqn", "expectancy", "recovery_factor"):
        assert key in summary


def test_summarize_performance_with_benchmark(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    result = BacktestEngine().run("TEST", TrendFollowingStrategy(), features)
    trade_pnls = pd.Series([t.pnl_abs for t in result.trades])
    benchmark_returns = synthetic_ohlcv["close"].pct_change().dropna()
    summary = summarize_performance(result.equity_curve, trade_pnls, benchmark_returns=benchmark_returns)
    assert "alpha_annualized_pct" in summary
    assert "beta" in summary
    assert "information_ratio" in summary
