"""Yahoo's news endpoint has changed shape across yfinance versions (older
flat article dicts vs. the current schema nesting most fields under a
"content" key), and this repo's sandbox has no network access to verify
the exact live response before shipping (see the docstring on
YFinanceProvider.get_news). These tests lock in that _extract_news_items
handles both shapes defensively and never raises on malformed input --
worst case is an empty news list, which can never break signal generation.
"""
import src.pipeline.daily_run as daily_run
from src.data.providers.yfinance_provider import _extract_news_items


def test_extract_news_items_handles_nested_content_schema():
    raw = [{
        "content": {
            "title": "Company beats earnings expectations",
            "provider": {"displayName": "Reuters"},
            "canonicalUrl": {"url": "https://example.com/a"},
            "pubDate": "2026-07-06T08:00:00Z",
        }
    }]
    items = _extract_news_items(raw)
    assert items == [{
        "title": "Company beats earnings expectations",
        "link": "https://example.com/a",
        "publisher": "Reuters",
        "published_at": "2026-07-06T08:00:00Z",
    }]


def test_extract_news_items_handles_flat_legacy_schema():
    raw = [{
        "title": "Legacy-shaped headline",
        "publisher": "Bloomberg",
        "link": "https://example.com/b",
        "providerPublishTime": 1735689600,
    }]
    items = _extract_news_items(raw)
    assert items == [{
        "title": "Legacy-shaped headline",
        "link": "https://example.com/b",
        "publisher": "Bloomberg",
        "published_at": 1735689600,
    }]


def test_extract_news_items_skips_articles_missing_title_or_link():
    raw = [
        {"content": {"provider": {"displayName": "NoTitle"}}},
        {"title": "Has title but no link"},
        None,
        "not even a dict",
        {"content": {"title": "Valid one", "canonicalUrl": {"url": "https://example.com/c"}}},
    ]
    items = _extract_news_items(raw)
    assert len(items) == 1
    assert items[0]["title"] == "Valid one"


def test_extract_news_items_respects_limit():
    raw = [{"content": {"title": f"Headline {i}", "canonicalUrl": {"url": f"https://x.com/{i}"}}} for i in range(10)]
    items = _extract_news_items(raw, limit=3)
    assert len(items) == 3


def test_extract_news_items_empty_or_none_input():
    assert _extract_news_items([]) == []
    assert _extract_news_items(None) == []


def test_load_news_skips_crypto_without_calling_provider(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("YFinanceProvider should not be called for crypto")

    monkeypatch.setattr(daily_run, "YFinanceProvider", lambda: type("P", (), {"get_news": _boom})())
    assert daily_run._load_news("BTC/USDT", "crypto") == []
