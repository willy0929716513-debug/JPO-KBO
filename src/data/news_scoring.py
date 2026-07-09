"""Transparent, deterministic keyword-based tagging of news headlines as
bullish/bearish/neutral. This is NOT a machine-learning or LLM sentiment
model, and deliberately so: every tag can be traced back to the exact words
in the headline that triggered it, so the dashboard can show its work
("為什麼") instead of asserting an unexplained score. No API key or paid
service required -- runs entirely offline against the headline text already
flowing through the pipeline via YFinanceProvider.get_news().
"""
from __future__ import annotations

BULLISH_KEYWORDS = [
    "surge", "surges", "surging", "soar", "soars", "soaring", "jump", "jumps",
    "jumping", "rally", "rallies", "rallying", "beat", "beats", "beating",
    "record high", "outperform", "outperforms", "upgrade", "upgraded",
    "raises target", "raise target", "raised target", "accelerate",
    "accelerates", "accelerating", "growth", "growing", "demand surges",
    "strong demand", "breakthrough", "expansion", "expands", "expanding",
    "profit jumps", "profits jump", "booming", "boom", "rebound", "rebounds",
    "buy rating", "bullish", "top pick", "best stock", "beat expectations",
    "exceeds expectations", "hits record",
]
BEARISH_KEYWORDS = [
    "plunge", "plunges", "plunging", "slump", "slumps", "slumping", "tumble",
    "tumbles", "tumbling", "crash", "crashes", "crashing", "downgrade",
    "downgraded", "cuts target", "cut target", "cuts forecast", "miss",
    "misses", "missing", "decline", "declines", "declining", "lawsuit",
    "investigation", "probe", "warns", "warning", "layoff", "layoffs",
    "recall", "recalls", "fraud", "bearish", "sell rating", "shortfall",
    "loss widens", "losses widen", "falls short", "disappointing",
]


def score_headline(title: str) -> dict:
    """Tags a single headline. Returns {"tone": "bullish"|"bearish"|"neutral",
    "matched_keywords": [...]}. Ties (equal bullish/bearish hits, including
    zero/zero) resolve to neutral rather than guessing a direction."""
    lowered = (title or "").lower()
    bullish_hits = [kw for kw in BULLISH_KEYWORDS if kw in lowered]
    bearish_hits = [kw for kw in BEARISH_KEYWORDS if kw in lowered]
    if len(bullish_hits) > len(bearish_hits):
        return {"tone": "bullish", "matched_keywords": bullish_hits}
    if len(bearish_hits) > len(bullish_hits):
        return {"tone": "bearish", "matched_keywords": bearish_hits}
    return {"tone": "neutral", "matched_keywords": []}


def score_news_batch(news_items: list[dict]) -> dict:
    """Tags each item in `news_items` in place (adds "tone"/"matched_keywords"
    keys) and returns an aggregate summary:
    {"score": float in [-1, 1], "bullish_count": int, "bearish_count": int}.
    `score` is (bullish_count - bearish_count) / total items; 0.0 when there's
    no news at all (neutral, not "unknown")."""
    if not news_items:
        return {"score": 0.0, "bullish_count": 0, "bearish_count": 0}
    bullish_count = 0
    bearish_count = 0
    for item in news_items:
        tagged = score_headline(item.get("title", ""))
        item["tone"] = tagged["tone"]
        item["matched_keywords"] = tagged["matched_keywords"]
        if tagged["tone"] == "bullish":
            bullish_count += 1
        elif tagged["tone"] == "bearish":
            bearish_count += 1
    total = len(news_items)
    score = (bullish_count - bearish_count) / total
    return {"score": round(score, 3), "bullish_count": bullish_count, "bearish_count": bearish_count}
