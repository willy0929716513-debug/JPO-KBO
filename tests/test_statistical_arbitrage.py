from src.strategies.statistical_arbitrage import KalmanHedgeRatio, PairsTradingStrategy, cointegration_test


def test_cointegration_test_detects_cointegrated_pair(cointegrated_pair):
    close_a, close_b = cointegrated_pair
    result = cointegration_test(close_a, close_b)
    assert result["cointegrated"] is True
    assert result["p_value"] < 0.05


def test_cointegration_test_rejects_independent_pair(independent_pair):
    close_a, close_b = independent_pair
    result = cointegration_test(close_a, close_b)
    assert result["cointegrated"] is False


def test_kalman_hedge_ratio_runs(cointegrated_pair):
    close_a, close_b = cointegrated_pair
    kf = KalmanHedgeRatio()
    out = kf.run(close_a, close_b)
    assert len(out) == len(close_a)
    assert {"beta", "alpha", "spread"}.issubset(out.columns)


def test_pairs_strategy_trades_cointegrated_pair(cointegrated_pair):
    close_a, close_b = cointegrated_pair
    strategy = PairsTradingStrategy(entry_z=1.0, exit_z=0.3, lookback=40)
    signal = strategy.analyze("A", close_a, "B", close_b)
    assert signal.cointegrated is True
    assert signal.action_a in ("BUY", "SELL", "HOLD")
    assert signal.action_b in ("BUY", "SELL", "HOLD")
    d = signal.to_dict()
    assert d["symbol_a"] == "A" and d["symbol_b"] == "B"


def test_pairs_strategy_holds_on_non_cointegrated_pair(independent_pair):
    close_a, close_b = independent_pair
    strategy = PairsTradingStrategy()
    signal = strategy.analyze("A", close_a, "B", close_b)
    assert signal.cointegrated is False
    assert signal.action_a == "HOLD"
    assert signal.action_b == "HOLD"
