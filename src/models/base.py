"""Shared model result type used across the ML layer."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class ModelResult:
    model_name: str
    accuracy: float
    precision: float
    recall: float
    f1: float
    feature_importance: dict[str, float] = field(default_factory=dict)
    predictions: np.ndarray | None = None
    probabilities: np.ndarray | None = None
