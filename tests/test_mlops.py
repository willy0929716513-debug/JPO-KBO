import numpy as np
import pandas as pd
import pytest

from src.mlops.champion_challenger import should_promote_challenger
from src.mlops.drift import detect_feature_drift, ks_test_drift, population_stability_index
from src.mlops.registry import ModelRegistry


def test_registry_save_load_roundtrip(tmp_path):
    registry = ModelRegistry(registry_dir=tmp_path)
    model = {"dummy": "model"}  # joblib can pickle arbitrary picklable objects
    meta = registry.save("test_model", model, metrics={"f1": 0.6}, feature_columns=["a", "b"], version="v1")
    assert meta.version == "v1"

    loaded_model, loaded_meta = registry.load("test_model", "v1")
    assert loaded_model == model
    assert loaded_meta.metrics["f1"] == 0.6


def test_registry_promote_sets_champion(tmp_path):
    registry = ModelRegistry(registry_dir=tmp_path)
    registry.save("m", {"x": 1}, {"f1": 0.5}, ["a"], version="v1")
    registry.save("m", {"x": 2}, {"f1": 0.6}, ["a"], version="v2")

    registry.promote("m", "v2")
    champion = registry.get_champion("m")
    assert champion is not None
    assert champion.version == "v2"

    registry.promote("m", "v1")
    champion = registry.get_champion("m")
    assert champion.version == "v1"


def test_promote_missing_version_raises(tmp_path):
    registry = ModelRegistry(registry_dir=tmp_path)
    registry.save("m", {"x": 1}, {"f1": 0.5}, ["a"], version="v1")
    with pytest.raises(FileNotFoundError):
        registry.promote("m", "does_not_exist")


def test_should_promote_challenger_no_champion():
    decision = should_promote_challenger({"f1": 0.5}, None)
    assert decision.promote is True


def test_should_promote_challenger_better_metric():
    decision = should_promote_challenger({"f1": 0.7}, {"f1": 0.5})
    assert decision.promote is True


def test_should_promote_challenger_worse_metric():
    decision = should_promote_challenger({"f1": 0.4}, {"f1": 0.5})
    assert decision.promote is False


def test_psi_low_for_identical_distributions():
    rng = np.random.default_rng(1)
    data = pd.Series(rng.normal(0, 1, 1000))
    psi = population_stability_index(data, data)
    assert psi < 0.01


def test_psi_high_for_shifted_distribution():
    rng = np.random.default_rng(1)
    reference = pd.Series(rng.normal(0, 1, 1000))
    shifted = pd.Series(rng.normal(5, 1, 1000))
    psi = population_stability_index(reference, shifted)
    assert psi > 0.25


def test_ks_test_drift_detects_shift():
    rng = np.random.default_rng(1)
    reference = pd.Series(rng.normal(0, 1, 500))
    shifted = pd.Series(rng.normal(3, 1, 500))
    result = ks_test_drift(reference, shifted)
    assert result["drifted"] is True


def test_detect_feature_drift_dataframe():
    rng = np.random.default_rng(1)
    reference = pd.DataFrame({"f1": rng.normal(0, 1, 200), "f2": rng.normal(0, 1, 200)})
    current = pd.DataFrame({"f1": rng.normal(5, 1, 200), "f2": rng.normal(0, 1, 200)})
    report = detect_feature_drift(reference, current)
    assert "f1" in report["feature"].values
    top_row = report.iloc[0]
    assert top_row["feature"] == "f1"  # most drifted feature sorted first
