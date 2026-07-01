"""End-to-end training routine: builds features, labels forward returns as
up/down, time-series-splits, trains the voting ensemble, and reports
out-of-sample metrics -- the "does this actually predict anything" check
that must pass before a strategy is trusted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import TimeSeriesSplit

from src.models.base import ModelResult
from src.models.ensemble import VotingEnsemble
from src.models.labeling import momentum_primary_side, triple_barrier_labels


def make_labels(df: pd.DataFrame, horizon: int = 5, threshold: float = 0.0) -> pd.Series:
    """1 if forward return over `horizon` bars exceeds `threshold`, else 0."""
    fwd_ret = df["close"].shift(-horizon) / df["close"] - 1
    return (fwd_ret > threshold).astype(int)


def train_direction_classifier(
    features: pd.DataFrame, horizon: int = 5, n_splits: int = 5,
) -> tuple[VotingEnsemble, ModelResult, list[str]]:
    labels = make_labels(features, horizon=horizon)
    feature_cols = [c for c in features.columns if c not in ("open", "high", "low", "close", "volume")]

    data = features[feature_cols].copy()
    data["__label__"] = labels
    data = data.replace([np.inf, -np.inf], np.nan).dropna()

    X, y = data[feature_cols], data["__label__"].astype(int)
    if len(X) < 100 or y.nunique() < 2:
        raise ValueError("Not enough clean data to train a model (need >=100 rows and both classes present).")

    tscv = TimeSeriesSplit(n_splits=n_splits)
    train_idx, test_idx = list(tscv.split(X))[-1]  # final split = most recent out-of-sample slice
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    ensemble = VotingEnsemble()
    ensemble.fit(X_train, y_train)

    proba = ensemble.predict_proba(X_test)[:, 1]
    preds = (proba >= 0.5).astype(int)

    result = ModelResult(
        model_name="voting_ensemble",
        accuracy=accuracy_score(y_test, preds),
        precision=precision_score(y_test, preds, zero_division=0),
        recall=recall_score(y_test, preds, zero_division=0),
        f1=f1_score(y_test, preds, zero_division=0),
        feature_importance=ensemble.feature_importance(feature_cols),
        predictions=preds,
        probabilities=proba,
    )
    return ensemble, result, feature_cols


def train_meta_labeling_model(
    features: pd.DataFrame, primary_side: pd.Series | None = None,
    pt_mult: float = 2.0, sl_mult: float = 2.0, max_holding: int = 10, n_splits: int = 5,
) -> tuple[VotingEnsemble, ModelResult, list[str], pd.DataFrame]:
    """Trains a secondary ('meta') classifier that predicts whether a
    primary directional signal is worth acting on, using triple-barrier
    labels as the target. If `primary_side` isn't supplied, falls back to
    a simple momentum sign as the primary model -- swap in an existing
    Strategy's BUY/SELL calls for a real deployment.

    Returns (meta_model, out-of-sample ModelResult, feature columns used,
    the triple-barrier label DataFrame) so callers can inspect realized
    trade outcomes, not just classifier metrics.
    """
    side = primary_side if primary_side is not None else momentum_primary_side(features["close"])
    barrier_df = triple_barrier_labels(features["close"], side, pt_mult, sl_mult, max_holding)

    if len(barrier_df) < 100:
        raise ValueError("Not enough triple-barrier events to train a meta-labeling model (need >=100).")

    feature_cols = [c for c in features.columns if c not in ("open", "high", "low", "close", "volume")]
    aligned = features.loc[barrier_df.index, feature_cols].copy()
    aligned["__label__"] = barrier_df["meta_label"].astype(int)
    aligned = aligned.replace([np.inf, -np.inf], np.nan).dropna()

    X, y = aligned[feature_cols], aligned["__label__"]
    if len(X) < 100 or y.nunique() < 2:
        raise ValueError("Not enough clean meta-labeling data to train (need >=100 rows and both classes present).")

    tscv = TimeSeriesSplit(n_splits=min(n_splits, max(2, len(X) // 50)))
    train_idx, test_idx = list(tscv.split(X))[-1]
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    meta_model = VotingEnsemble()
    meta_model.fit(X_train, y_train)

    proba = meta_model.predict_proba(X_test)[:, 1]
    preds = (proba >= 0.5).astype(int)

    result = ModelResult(
        model_name="meta_labeling_ensemble",
        accuracy=accuracy_score(y_test, preds),
        precision=precision_score(y_test, preds, zero_division=0),
        recall=recall_score(y_test, preds, zero_division=0),
        f1=f1_score(y_test, preds, zero_division=0),
        feature_importance=meta_model.feature_importance(feature_cols),
        predictions=preds,
        probabilities=proba,
    )
    return meta_model, result, feature_cols, barrier_df
