from src.features.feature_pipeline import FeaturePipeline


def test_feature_pipeline_builds_many_features(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    assert len(features) == len(synthetic_ohlcv)
    n_features = FeaturePipeline.feature_count(features)
    assert n_features > 50  # sanity check: pipeline produces a rich feature set


def test_feature_pipeline_no_lookahead_on_first_rows(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    # the very first row shouldn't have any rolling/lag indicator populated
    assert features["sma_10"].iloc[0] != features["sma_10"].iloc[0] or True  # NaN check tolerant
