"""Reads free macro data (FRED, when configured) and crypto Fear & Greed
sentiment to form a broad market-tone opinion. Deliberately kept
low-confidence and slow-moving -- macro data updates monthly/quarterly, not
daily, so it should nudge the decision, never dominate it.
"""
from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentOpinion


class MacroAgent(Agent):
    name = "macro_agent"

    def analyze(self, context: AgentContext) -> AgentOpinion:
        macro = context.macro_snapshot or {}
        sentiment = context.sentiment_snapshot or {}

        reasons: list[str] = []
        lean = 0.0
        have_signal = False

        fed_rate = macro.get("fed_funds_rate")
        if fed_rate is not None:
            reasons.append(f"Fed funds rate={fed_rate:.2f}% (informational -- not used for timing)")

        fear_greed = sentiment.get("crypto_fear_greed", {})
        fg_value = fear_greed.get("value")
        if fg_value is not None:
            # Contrarian-leaning heuristic: extremes in crowd sentiment tend to precede mean reversion.
            if fg_value <= 25:
                lean += 0.3
                reasons.append(f"Fear & Greed={fg_value} (extreme fear -- mild contrarian bullish lean)")
            elif fg_value >= 75:
                lean -= 0.3
                reasons.append(f"Fear & Greed={fg_value} (extreme greed -- mild contrarian bearish lean)")
            else:
                reasons.append(f"Fear & Greed={fg_value} (neutral zone, no lean)")
            have_signal = True

        if not have_signal:
            return AgentOpinion(self.name, 0.0, 0.0,
                                 reasons=reasons or ["No macro/sentiment data available "
                                                      "(optional FRED_API_KEY not configured)"])

        return AgentOpinion(self.name, lean, 0.25, reasons=reasons)
