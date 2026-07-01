"""Voting / stacking ensemble across multiple tree models, with basic
probability calibration so the output can be interpreted as a real
confidence level rather than a raw score.
"""
from __future__ import annotations

import numpy as np

from src.models.tree_models import TreeModelFactory


class VotingEnsemble:
    """Soft-voting ensemble of XGBoost + LightGBM + RandomForest classifiers."""

    def __init__(self, kinds: list[str] | None = None, calibrate: bool = True):
        self.kinds = kinds or ["xgboost", "lightgbm", "random_forest"]
        self.calibrate = calibrate
        self.models: dict[str, object] = {}

    def fit(self, X, y) -> "VotingEnsemble":
        from sklearn.calibration import CalibratedClassifierCV

        for kind in self.kinds:
            base = TreeModelFactory.create(kind, task="classification")
            if self.calibrate:
                model = CalibratedClassifierCV(base, method="sigmoid", cv=3)
            else:
                model = base
            model.fit(X, y)
            self.models[kind] = model
        return self

    def predict_proba(self, X) -> np.ndarray:
        probs = [m.predict_proba(X) for m in self.models.values()]
        return np.mean(probs, axis=0)

    def predict(self, X) -> np.ndarray:
        proba = self.predict_proba(X)
        return np.argmax(proba, axis=1)

    def feature_importance(self, feature_names: list[str]) -> dict[str, float]:
        importances = np.zeros(len(feature_names))
        n = 0
        for model in self.models.values():
            inner = getattr(model, "estimator", model)
            inner = getattr(inner, "base_estimator", inner)
            fi = getattr(inner, "feature_importances_", None)
            if fi is not None and len(fi) == len(feature_names):
                importances += np.asarray(fi)
                n += 1
        if n == 0:
            return {}
        importances /= n
        return dict(sorted(zip(feature_names, importances.tolist()), key=lambda kv: -kv[1]))
