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
        confidence = 0.0

        fed_rate = macro.get("fed_funds_rate")
        if fed_rate is not None:
            reasons.append(f"Fed funds rate={fed_rate:.2f}% (informational -- not used for timing)")

        # Crypto Fear & Greed is a crypto-market-specific crowd-sentiment
        # gauge -- it says something real about Bitcoin/Ethereum psychology,
        # but was previously applied as a contrarian lean to EVERY symbol
        # regardless of asset class. At its usual 0.25 confidence (comparable
        # to or larger than many technical_agent readings), that silently
        # pushed Taiwan equities/gold/oil/forex scores around by an amount
        # unrelated to that asset -- e.g. it happened to nearly cancel out a
        # legitimate technical SELL signal on gold futures just because
        # crypto sentiment read "extreme fear" that day. Scoped to crypto
        # symbols only now.
        asset_class = (context.asset_class_of or {}).get(context.symbol)
        if asset_class == "crypto":
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
                confidence = 0.25

        if not reasons:
            return AgentOpinion(self.name, 0.0, 0.0,
                                 reasons=["No macro/sentiment data available "
                                          "(optional FRED_API_KEY not configured)"])

        return AgentOpinion(self.name, lean, confidence, reasons=reasons)
