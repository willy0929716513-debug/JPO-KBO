"""Feature/data drift detection: flags when live feature distributions have
shifted meaningfully from what a model was trained on. This is usually a
better early-warning signal for 'this model needs retraining' than waiting
for live accuracy to visibly degrade, since accuracy is only observable in
arrears (after enough labeled outcomes accumulate) while drift is visible immediately.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def population_stability_index(reference: pd.Series, current: pd.Series, bins: int = 10) -> float:
    """PSI: standard drift metric. <0.1 = no significant shift, 0.1-0.25 =
    moderate shift (investigate), >0.25 = major shift (retrain)."""
    reference, current = reference.dropna(), current.dropna()
    if reference.empty or current.empty:
        return 0.0

    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:
        return 0.0

    ref_counts, _ = np.histogram(reference, bins=edges)
    cur_counts, _ = np.histogram(current, bins=edges)

    ref_pct = np.clip(ref_counts / max(ref_counts.sum(), 1), 1e-6, None)
    cur_pct = np.clip(cur_counts / max(cur_counts.sum(), 1), 1e-6, None)

    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def ks_test_drift(reference: pd.Series, current: pd.Series) -> dict:
    """Two-sample Kolmogorov-Smirnov test: p < 0.05 suggests the current
    distribution differs significantly from the reference distribution."""
    from scipy.stats import ks_2samp

    reference, current = reference.dropna(), current.dropna()
    if len(reference) < 10 or len(current) < 10:
        return {"statistic": 0.0, "p_value": 1.0, "drifted": False}

    stat, p_value = ks_2samp(reference, current)
    return {"statistic": float(stat), "p_value": float(p_value), "drifted": bool(p_value < 0.05)}


def detect_feature_drift(reference_features: pd.DataFrame, current_features: pd.DataFrame,
                          psi_threshold: float = 0.25) -> pd.DataFrame:
    """Runs PSI + KS test on every shared numeric column, returns a summary
    table sorted by PSI descending (most-drifted features first) -- scan
    this after retraining to catch upstream data-quality regressions, not
    just genuine market regime shifts."""
    shared_cols = [c for c in reference_features.columns if c in current_features.columns]
    rows = []
    for col in shared_cols:
        ref_col, cur_col = reference_features[col], current_features[col]
        if not pd.api.types.is_numeric_dtype(ref_col):
            continue
        psi = population_stability_index(ref_col, cur_col)
        ks = ks_test_drift(ref_col, cur_col)
        rows.append({"feature": col, "psi": round(psi, 4), "psi_drifted": psi > psi_threshold,
                     "ks_p_value": round(ks["p_value"], 4), "ks_drifted": ks["drifted"]})

    if not rows:
        return pd.DataFrame(columns=["feature", "psi", "psi_drifted", "ks_p_value", "ks_drifted"])
    return pd.DataFrame(rows).sort_values("psi", ascending=False).reset_index(drop=True)
