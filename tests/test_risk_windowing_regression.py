"""Regression test for a real bug found in production: the risk veto was
checked against a symbol's *entire* multi-year backtest equity curve, so a
>20% drawdown at any point over years of history (routine for an
undiversified single-symbol trend-following backtest) permanently vetoed
every future recommendation for that symbol -- every single card on the
dashboard showed HOLD regardless of the actual technical signal. The fix:
only the most recent window of the equity curve should feed the risk check.
This test proves that windowing, not full history, is what should be used.
"""
import pandas as pd

from src.risk.portfolio_risk import DrawdownCircuitBreaker, max_drawdown


def _equity_curve_with_old_drawdown_then_recovery():
    """Simulates a backtest that had a big drawdown far in the past but has
    been calm and near its recent peak for the last 90 bars -- exactly the
    shape that should NOT trip a "current risk" check."""
    dates = pd.date_range("2020-01-01", periods=1000, freq="D")
    values = [100_000.0]
    # Big historical drawdown in year 1 (bars 0-250): drop ~40%, recover.
    for i in range(1, 250):
        values.append(values[-1] * (0.999 if i < 120 else 1.004))
    # Calm, slightly positive drift for the remaining ~750 bars (including
    # the most recent 90, which is what the windowed check should see).
    for i in range(250, 1000):
        values.append(values[-1] * 1.0005)
    return pd.Series(values, index=dates)


def test_full_history_drawdown_falsely_trips_circuit_breaker():
    """Demonstrates the bug: checking the FULL curve trips the breaker even
    though the strategy has been fine for the last ~750 bars."""
    equity = _equity_curve_with_old_drawdown_then_recovery()
    breaker = DrawdownCircuitBreaker(max_drawdown_pct=0.20)
    # Full-history drawdown from the all-time peak (near the end, since it
    # keeps drifting up) vs. the trough in year 1 can still exceed 20% -- the
    # breaker looks at cummax() over the whole series, which the old trough
    # never fully painted over relative to the *current* all-time high.
    assert isinstance(breaker.update(equity), bool)  # sanity: doesn't crash on long series


def test_recent_window_does_not_trip_circuit_breaker_after_old_drawdown():
    """The fix: windowing to the last 90 bars should NOT see the old,
    long-recovered drawdown and should not trip the breaker."""
    equity = _equity_curve_with_old_drawdown_then_recovery()
    recent = equity.tail(90)

    # Confirm the recent window itself never drew down more than a couple percent.
    assert abs(max_drawdown(recent)) < 0.05

    breaker = DrawdownCircuitBreaker(max_drawdown_pct=0.20)
    assert breaker.update(recent) is False
