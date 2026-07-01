import pandas as pd

from src.execution.algos import simulate_pov_execution, simulate_twap_execution, simulate_vwap_execution
from src.execution.simulated_orders import simulate_bracket_order, simulate_oco_order, simulate_trailing_stop


def _make_bars(prices: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    volumes = volumes or [1_000_000.0] * len(prices)
    return pd.DataFrame({
        "open": prices, "high": [p * 1.01 for p in prices], "low": [p * 0.99 for p in prices],
        "close": prices, "volume": volumes,
    }, index=idx)


def test_bracket_order_hits_take_profit():
    bars = _make_bars([100, 101, 103, 105, 108])
    result = simulate_bracket_order(bars, entry_price=100, direction=1, take_profit=104, stop_loss=95)
    assert result.triggered is True
    assert result.trigger_type == "take_profit"


def test_bracket_order_hits_stop_loss():
    bars = _make_bars([100, 98, 96, 94, 92])
    result = simulate_bracket_order(bars, entry_price=100, direction=1, take_profit=110, stop_loss=97)
    assert result.trigger_type == "stop_loss"


def test_bracket_order_time_limit():
    bars = _make_bars([100, 100.5, 100.2, 100.8, 100.3])
    result = simulate_bracket_order(bars, entry_price=100, direction=1, take_profit=200, stop_loss=1)
    assert result.trigger_type == "time_limit"


def test_oco_order_triggers_on_first_touch():
    bars = _make_bars([100, 102, 104, 106])
    result = simulate_oco_order(bars, level_a=105, level_b=95)
    assert result.triggered is True


def test_trailing_stop_triggers_after_pullback():
    bars = _make_bars([100, 105, 110, 108, 104, 100])
    result = simulate_trailing_stop(bars, entry_price=100, direction=1, trail_amount=5)
    assert result.triggered is True
    assert result.trigger_type in ("trailing_stop", "time_limit")


def test_twap_execution_report():
    bars = _make_bars([100, 101, 99, 102, 100])
    report = simulate_twap_execution(bars, total_quantity=500, side="buy")
    assert report.algo == "TWAP"
    assert report.total_quantity == 500
    assert len(report.child_fills) == 5
    d = report.to_dict()
    assert "slippage_vs_benchmark_bps" in d


def test_vwap_execution_report():
    bars = _make_bars([100, 101, 99, 102, 100], volumes=[1000, 2000, 500, 3000, 1500])
    report = simulate_vwap_execution(bars, total_quantity=1000, side="sell")
    assert report.algo == "VWAP"
    total_filled = sum(f["quantity"] for f in report.child_fills)
    assert abs(total_filled - 1000) < 1e-6


def test_pov_execution_report():
    bars = _make_bars([100, 101, 99, 102, 100], volumes=[1000, 2000, 500, 3000, 1500])
    report = simulate_pov_execution(bars, total_quantity=200, side="buy", participation_rate=0.5)
    assert report.algo == "POV"
    assert report.total_quantity <= 200 + 1e-6
