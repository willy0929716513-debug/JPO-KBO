"""Probability calibration helpers: turns raw model scores into
well-calibrated probabilities, and derives a discrete confidence label
used when presenting signals to the user."""
from __future__ import annotations

import numpy as np


def confidence_label(probability: float) -> str:
    if probability >= 0.75:
        return "very_high"
    if probability >= 0.6:
        return "high"
    if probability >= 0.5:
        return "moderate"
    return "low"


def brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Lower is better calibrated. 0 = perfect, 0.25 = coin flip baseline."""
    return float(np.mean((y_prob - y_true) ** 2))
