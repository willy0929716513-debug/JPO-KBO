"""Thin, uniform wrappers around XGBoost / LightGBM / RandomForest so the
rest of the system can treat them interchangeably (all expose
.fit / .predict / .predict_proba / .feature_importances_).
"""
from __future__ import annotations

from typing import Any, Literal

ModelKind = Literal["xgboost", "lightgbm", "random_forest"]


class TreeModelFactory:
    @staticmethod
    def create(kind: ModelKind, task: Literal["classification", "regression"] = "classification", **kwargs) -> Any:
        if kind == "xgboost":
            import xgboost as xgb
            cls = xgb.XGBClassifier if task == "classification" else xgb.XGBRegressor
            defaults = dict(n_estimators=300, max_depth=4, learning_rate=0.05,
                             subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                             eval_metric="logloss" if task == "classification" else "rmse",
                             n_jobs=-1)
            defaults.update(kwargs)
            return cls(**defaults)

        if kind == "lightgbm":
            import lightgbm as lgb
            cls = lgb.LGBMClassifier if task == "classification" else lgb.LGBMRegressor
            defaults = dict(n_estimators=300, max_depth=-1, num_leaves=31,
                             learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                             verbosity=-1, n_jobs=-1)
            defaults.update(kwargs)
            return cls(**defaults)

        if kind == "random_forest":
            from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
            cls = RandomForestClassifier if task == "classification" else RandomForestRegressor
            defaults = dict(n_estimators=400, max_depth=8, min_samples_leaf=20, n_jobs=-1)
            defaults.update(kwargs)
            return cls(**defaults)

        raise ValueError(f"Unknown model kind: {kind}")
