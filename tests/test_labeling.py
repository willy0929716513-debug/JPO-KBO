import numpy as np

from src.features.feature_pipeline import FeaturePipeline
from src.models.labeling import daily_volatility, momentum_primary_side, triple_barrier_labels
from src.models.train import train_meta_labeling_model


def test_daily_volatility_positive(synthetic_ohlcv):
    vol = daily_volatility(synthetic_ohlcv["close"])
    assert (vol.dropna() >= 0).all()


def test_momentum_primary_side_values(synthetic_ohlcv):
    side = momentum_primary_side(synthetic_ohlcv["close"])
    assert set(side.dropna().unique()).issubset({-1.0, 0.0, 1.0})


def test_triple_barrier_labels_shape_and_values(synthetic_ohlcv):
    side = momentum_primary_side(synthetic_ohlcv["close"])
    labels = triple_barrier_labels(synthetic_ohlcv["close"], side, pt_mult=2.0, sl_mult=2.0, max_holding=10)
    assert not labels.empty
    assert set(labels["outcome_label"].unique()).issubset({-1, 0, 1})
    assert set(labels["meta_label"].unique()).issubset({0, 1})
    assert (labels["holding_bars"] <= 10).all()


def test_triple_barrier_labels_empty_when_no_signal(synthetic_ohlcv):
    import pandas as pd
    flat_side = pd.Series(0, index=synthetic_ohlcv.index)
    labels = triple_barrier_labels(synthetic_ohlcv["close"], flat_side)
    assert labels.empty


def test_train_meta_labeling_model_runs(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    model, result, feature_cols, barrier_df = train_meta_labeling_model(features, max_holding=5)
    assert result.model_name == "meta_labeling_ensemble"
    assert 0.0 <= result.accuracy <= 1.0
    assert len(feature_cols) > 0
    assert not barrier_df.empty
