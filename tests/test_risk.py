import pandas as pd

from src.risk.position_sizing import atr_based_size, fixed_fractional_size, kelly_fraction
from src.risk.portfolio_risk import conditional_var, historical_var, max_drawdown, risk_of_ruin
from src.risk.stops import atr_stop, dynamic_take_profit


def test_kelly_fraction_bounds():
    f = kelly_fraction(win_rate=0.55, avg_win=100, avg_loss=80, kelly_cap=0.5)
    assert 0.0 <= f <= 0.5


def test_kelly_fraction_negative_edge_is_zero():
    f = kelly_fraction(win_rate=0.3, avg_win=50, avg_loss=100)
    assert f == 0.0


def test_fixed_fractional_size():
    size = fixed_fractional_size(capital=100_000, risk_pct=0.01, entry_price=100, stop_price=95)
    assert size == 1000 / 5


def test_atr_based_size_positive():
    size = atr_based_size(capital=100_000, risk_pct=0.01, atr=2.0, atr_multiplier=2.0)
    assert size > 0


def test_atr_stop_direction():
    long_stop = atr_stop(entry_price=100, atr=2, direction=1, multiplier=2)
    short_stop = atr_stop(entry_price=100, atr=2, direction=-1, multiplier=2)
    assert long_stop < 100 < short_stop


def test_dynamic_take_profit():
    tp = dynamic_take_profit(entry_price=100, atr=2, direction=1, reward_risk_ratio=2, stop_multiplier=2)
    assert tp > 100


def test_max_drawdown():
    equity = pd.Series([100, 110, 90, 95, 120])
    mdd = max_drawdown(equity)
    assert mdd < 0


def test_var_and_cvar_ordering():
    returns = pd.Series([-0.05, -0.02, 0.01, 0.03, -0.1, 0.02, -0.01])
    var = historical_var(returns, confidence=0.95)
    cvar = conditional_var(returns, confidence=0.95)
    assert cvar >= var - 1e-9


def test_risk_of_ruin_bounds():
    r = risk_of_ruin(win_rate=0.55, win_loss_ratio=1.5, risk_per_trade=0.01)
    assert 0.0 <= r <= 1.0
