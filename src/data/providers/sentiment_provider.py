"""Market sentiment data.

- Crypto Fear & Greed Index: free, no key, via alternative.me.
- News / Reddit / Twitter(X) / Google Trends hooks are provided as a
  pluggable interface (`NewsSentimentSource`) so you can wire in your own
  paid API keys (NewsAPI, Twitter API v2, PRAW, pytrends) without touching
  the rest of the pipeline. They return neutral/empty results until wired up.
"""
from __future__ import annotations

import logging
from typing import Protocol

import requests

logger = logging.getLogger(__name__)

FEAR_GREED_URL = "https://api.alternative.me/fng/"


class NewsSentimentSource(Protocol):
    def score(self, query: str) -> float:
        """Return a sentiment score in [-1, 1]. -1 = very bearish, 1 = very bullish."""
        ...


class SentimentProvider:
    def get_crypto_fear_greed(self) -> dict:
        try:
            resp = requests.get(FEAR_GREED_URL, params={"limit": 1}, timeout=10)
            resp.raise_for_status()
            data = resp.json()["data"][0]
            return {
                "value": int(data["value"]),
                "classification": data["value_classification"],
            }
        except Exception as exc:
            logger.warning("Fear & Greed fetch failed: %s", exc)
            return {"value": None, "classification": "unknown"}

    def get_news_sentiment(self, query: str, source: NewsSentimentSource | None = None) -> float:
        """Plug in a real NewsSentimentSource (e.g. wrapping NewsAPI + a
        FinBERT model) via the `source` argument. Defaults to neutral (0.0)
        so the pipeline never breaks when no news API key is configured.
        """
        if source is None:
            return 0.0
        try:
            return source.score(query)
        except Exception as exc:
            logger.warning("news sentiment fetch failed for %s: %s", query, exc)
            return 0.0

    def get_social_sentiment(self, query: str, source: NewsSentimentSource | None = None) -> float:
        """Same pattern as get_news_sentiment, for Reddit/Twitter/Google Trends
        integrations. Wire in PRAW / Twitter API v2 / pytrends here."""
        return self.get_news_sentiment(query, source)
