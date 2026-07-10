"""Best-effort detection of ad-hoc Taiwan Stock Exchange (TWSE) closures
that market_hours.py's plain weekday+clock heuristic can't know about --
most notably "颱風假" (typhoon days), where the Taipei city government
declares a same-day work/school stoppage due to weather and TWSE follows
suit, closing the whole market for the day. These are announced the
morning of and are impossible to encode in any static holiday calendar in
advance.

TWSE publishes its holiday/closure schedule at a public URL, updated same-
day for ad-hoc closures. This repo's sandbox has no general internet
access to verify that endpoint's exact live response shape before shipping
(same caveat as YFinanceProvider.get_news's docstring, for a different
provider) -- so rather than parsing a guessed JSON/HTML structure with
confident field-name assumptions, this does a maximally permissive
substring search over the raw response text: if today's date appears on
the same line as a closure keyword ("休市"), treat today as closed.

Any failure at all (network error, timeout, unexpected/empty content) is
swallowed and treated as "no known ad-hoc closure" -- this can only ever
narrow an "open" verdict down to "closed" on a real, confirmed closure day;
it can never invent a false closure that overrides genuine trading hours,
and a broken/blocked endpoint just silently falls back to the pre-existing
weekday+clock behavior.
"""
from __future__ import annotations

import logging
import time
from datetime import date

logger = logging.getLogger(__name__)

_HOLIDAY_SCHEDULE_URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
_CLOSURE_KEYWORDS = ("休市", "停止交易")


class TaiwanHolidayProvider:
    """Caches its check per calendar date so this adds at most one network
    call per day, not one per 5-minute pipeline tick."""

    def __init__(self, cache_ttl_seconds: int = 6 * 3600):
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_for_date: date | None = None
        self._cached_result: bool = False
        self._last_fetch_monotonic: float = float("-inf")

    def is_closed_today(self, today: date | None = None) -> bool:
        today = today or date.today()
        now = time.monotonic()
        stale = (now - self._last_fetch_monotonic) > self.cache_ttl_seconds
        if self._cached_for_date != today or stale:
            self._cached_result = self._check(today)
            self._cached_for_date = today
            self._last_fetch_monotonic = now
        return self._cached_result

    def _check(self, today: date) -> bool:
        try:
            import requests

            resp = requests.get(_HOLIDAY_SCHEDULE_URL, params={"response": "csv"}, timeout=5)
            resp.raise_for_status()
            text = resp.text
        except Exception as exc:
            logger.warning("TWSE holiday schedule fetch failed, assuming no ad-hoc closure today: %s", exc)
            return False
        return _text_marks_date_closed(text, today)


def _text_marks_date_closed(text: str, today: date) -> bool:
    date_markers = {
        today.strftime("%Y/%m/%d"), today.strftime("%Y-%m-%d"), today.strftime("%Y%m%d"),
        f"{today.year - 1911}/{today.month:02d}/{today.day:02d}",  # ROC (Minguo) calendar, e.g. "115/07/10"
        f"{today.year - 1911}年{today.month}月{today.day}日",
    }
    for line in text.splitlines():
        if any(marker in line for marker in date_markers) and any(kw in line for kw in _CLOSURE_KEYWORDS):
            return True
    return False
