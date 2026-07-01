import numpy as np
import pandas as pd

from src.risk.limits import LossLimitConfig, LossLimitMonitor
from src.risk.portfolio_risk import check_correlation_limit, check_exposure_limits, portfolio_conditional_var, portfolio_var


def test_loss_limit_monitor_no_breach_on_flat_equity():
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    equity = pd.Series(100_000.0, index=dates)
    status = LossLimitMonitor().check(equity)
    assert status.halted is False


def test_loss_limit_monitor_detects_daily_breach():
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    equity = pd.Series([100_000, 100_000, 100_000, 100_000, 90_000], index=dates, dtype=float)
    status = LossLimitMonitor(LossLimitConfig(daily_loss_limit_pct=0.03)).check(equity)
    assert status.halted is True
    assert "daily" in status.breached


def test_check_correlation_limit_flags_high_correlation():
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    base = pd.Series(np.random.default_rng(1).normal(0, 0.01, 100), index=idx)
    returns = {"A": base, "B": base * 1.01 + 0.0001}  # near-identical -> highly correlated
    result = check_correlation_limit(returns, max_avg_correlation=0.5)
    assert result["breached"] is True


def test_check_exposure_limits_flags_overweight_group():
    weights = {"BTC/USDT": 0.5, "ETH/USDT": 0.3, "AAPL": 0.2}
    group_of = {"BTC/USDT": "crypto", "ETH/USDT": "crypto", "AAPL": "equity"}
    result = check_exposure_limits(weights, group_of, max_group_weight=0.4)
    assert result["breached"] is True
    assert "crypto" in result["breaches"]


def test_portfolio_var_and_cvar_nonnegative():
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    rng = np.random.default_rng(3)
    returns = {"A": pd.Series(rng.normal(0, 0.02, 100), index=idx),
               "B": pd.Series(rng.normal(0, 0.015, 100), index=idx)}
    weights = {"A": 0.6, "B": 0.4}
    var = portfolio_var(weights, returns)
    cvar = portfolio_conditional_var(weights, returns)
    assert var >= 0
    assert cvar >= var - 1e-9
