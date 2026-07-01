"""Multi-asset portfolio allocation across stocks / ETF / gold / crypto / FX:
equal-weight, inverse-volatility (simple risk parity), and vol-targeting.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class PortfolioAllocator:
    def __init__(self, max_position_weight: float = 0.25, max_asset_class_weight: float = 0.5):
        self.max_position_weight = max_position_weight
        self.max_asset_class_weight = max_asset_class_weight

    def equal_weight(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        w = min(1 / len(symbols), self.max_position_weight)
        weights = {s: w for s in symbols}
        return self._normalize(weights)

    def inverse_volatility(self, returns: dict[str, pd.Series]) -> dict[str, float]:
        """Simple risk-parity approximation: weight inversely proportional to
        realized volatility, so every asset contributes similar risk."""
        vols = {s: r.std() for s, r in returns.items() if not r.empty and r.std() > 0}
        if not vols:
            return self.equal_weight(list(returns.keys()))
        inv_vol = {s: 1 / v for s, v in vols.items()}
        total = sum(inv_vol.values())
        weights = {s: min(v / total, self.max_position_weight) for s, v in inv_vol.items()}
        return self._normalize(weights)

    def apply_asset_class_caps(self, weights: dict[str, float], asset_class_of: dict[str, str]) -> dict[str, float]:
        """Scales down any asset class that exceeds `max_asset_class_weight`.
        Deliberately does NOT renormalize back to sum=1 afterwards -- doing so
        would proportionally scale the just-capped class back up and defeat
        the cap. Any weight removed from an over-allocated class is left
        unallocated (effectively cash) rather than silently reassigned.
        """
        class_totals: dict[str, float] = {}
        for s, w in weights.items():
            cls = asset_class_of.get(s, "other")
            class_totals[cls] = class_totals.get(cls, 0) + w

        capped = dict(weights)
        for cls, total in class_totals.items():
            if total > self.max_asset_class_weight and total > 0:
                scale = self.max_asset_class_weight / total
                for s, w in weights.items():
                    if asset_class_of.get(s, "other") == cls:
                        capped[s] = w * scale
        return {s: round(w, 4) for s, w in capped.items()}

    @staticmethod
    def _normalize(weights: dict[str, float]) -> dict[str, float]:
        total = sum(weights.values())
        if total <= 0:
            return weights
        return {s: round(w / total, 4) for s, w in weights.items()}
