from src.features.feature_pipeline import FeaturePipeline
from src.strategies import (
    Action, BreakoutStrategy, MeanReversionStrategy, MomentumStrategy,
    StrategyCombiner, TrendFollowingStrategy,
)
from src.regime import RegimeDetector


def test_all_strategies_produce_valid_signal(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    for strat in [TrendFollowingStrategy(), MeanReversionStrategy(), BreakoutStrategy(), MomentumStrategy()]:
        sig = strat.generate_signal("TEST", features)
        assert sig.action in (Action.BUY, Action.SELL, Action.HOLD)
        assert 0.0 <= sig.confidence <= 1.0
        assert sig.price > 0


def test_combiner_produces_combined_signal(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    regime_state = RegimeDetector().detect(synthetic_ohlcv)
    combiner = StrategyCombiner([TrendFollowingStrategy(), MeanReversionStrategy(), BreakoutStrategy(), MomentumStrategy()])
    combined = combiner.combine("TEST", features, regime_state)
    assert combined.final_action in (Action.BUY, Action.SELL, Action.HOLD)
    assert len(combined.votes) == 4
    d = combined.to_dict()
    assert d["symbol"] == "TEST"
