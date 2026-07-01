"""Champion/challenger model comparison: decides whether a newly trained
challenger model should replace the current champion, based on out-of-sample
metrics rather than 'the newest model wins' -- guards against silently
degrading signal quality every time the daily retraining job runs.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromotionDecision:
    promote: bool
    reason: str
    champion_metric: float | None
    challenger_metric: float

    def to_dict(self) -> dict:
        return {
            "promote": self.promote, "reason": self.reason,
            "champion_metric": self.champion_metric, "challenger_metric": self.challenger_metric,
        }


def should_promote_challenger(
    challenger_metrics: dict, champion_metrics: dict | None,
    primary_metric: str = "f1", min_improvement: float = 0.0,
) -> PromotionDecision:
    challenger_value = challenger_metrics.get(primary_metric)
    if challenger_value is None:
        return PromotionDecision(False, f"Challenger metrics missing '{primary_metric}'", None, 0.0)

    if champion_metrics is None:
        return PromotionDecision(True, "No existing champion -- challenger promoted by default",
                                  None, challenger_value)

    champion_value = champion_metrics.get(primary_metric, 0.0)
    if challenger_value >= champion_value + min_improvement:
        return PromotionDecision(
            True, f"Challenger {primary_metric}={challenger_value:.4f} beats champion "
                  f"{champion_value:.4f} by >= {min_improvement}",
            champion_value, challenger_value,
        )
    return PromotionDecision(
        False, f"Challenger {primary_metric}={challenger_value:.4f} does not beat champion "
               f"{champion_value:.4f} by >= {min_improvement}",
        champion_value, challenger_value,
    )
