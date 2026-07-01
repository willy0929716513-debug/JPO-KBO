"""Feature registry: a simple decorator-based system so new features can be
added anywhere in the codebase and automatically picked up by the
FeaturePipeline, instead of hard-coding one giant function.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

FeatureFn = Callable[[pd.DataFrame], pd.DataFrame]

_REGISTRY: dict[str, FeatureFn] = {}


def register_feature(name: str):
    def decorator(fn: FeatureFn) -> FeatureFn:
        _REGISTRY[name] = fn
        return fn
    return decorator


def get_registry() -> dict[str, FeatureFn]:
    return dict(_REGISTRY)
