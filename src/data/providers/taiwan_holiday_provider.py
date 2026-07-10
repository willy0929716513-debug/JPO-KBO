"""Best-effort check for ad-hoc Taiwan Stock Exchange (TWSE) closures that
market_hours.py's plain weekday+clock heuristic can't know about -- most
notably "颱風假" (typhoon days), where the Taipei city government declares
a same-day work/school stoppage due to weather and TWSE follows suit,
closing the whole market for the day. These are announced the morning of
and are impossible to encode in any static holiday calendar in advance.

An earlier version of this scraped TWSE's own published holiday-schedule
page directly, but that could never be verified from this repo's sandbox
(no general internet access here -- even a plain `curl example.com` fails,
and WebFetch got a 403 from twse.com.tw), and in production it silently
never detected a real, confirmed closure (2026-07-10, Typhoon Bawi) --
either the endpoint isn't reachable from the pipeline's runner either, or
its actual response shape doesn't match what was guessed. Rather than keep
guessing at an unverifiable third-party endpoint, this now reuses the one
data source already proven to work end-to-end in this exact pipeline:
yfinance intraday bars for the TAIEX index (^TWII). If the market is
genuinely closed today (holiday or ad-hoc typhoon closure), there is
*zero* intraday trading, so no 1-minute bar for today will ever appear --
regardless of why it's closed. This sidesteps needing to know *why* the
market is closed at all.

Still fails safe the same way as before: any error (network failure,
empty data, unexpected shape) is treated as "no confirmed closure", so a
data hiccup can only ever leave the existing weekday+clock behavior
unchanged -- never invents a false closure on a real trading day.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TAIPEI = ZoneInfo("Asia/Taipei")
_TAIEX_SYMBOL = "^TWII"
# Give the market a few minutes after the 09:00 open before trusting an
# absence of intraday bars as "closed" -- yfinance's intraday feed isn't
# instantaneous, and checking too close to the opening bell on a genuinely
# open day could otherwise look identical to a closed one.
_GRACE_MINUTES_AFTER_OPEN = 15


class TaiwanHolidayProvider:
    """Caches its check per calendar date so this adds at most one extra
    intraday data fetch per day, not one per 5-minute pipeline tick."""

    def __init__(self, cache_ttl_seconds: int = 6 * 3600):
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_for_date: date | None = None
        self._cached_result: bool = False
        self._last_fetch_monotonic: float = float("-inf")

    def is_closed_today(self, today: date | None = None) -> bool:
        today = today or date.today()
        now_taipei = datetime.now(_TAIPEI)
        if now_taipei.date() == today:
            opened_at = now_taipei.replace(hour=9, minute=0, second=0, microsecond=0)
            if now_taipei < opened_at + timedelta(minutes=_GRACE_MINUTES_AFTER_OPEN):
                return False  # too early to trust an empty intraday feed either way

        now = time.monotonic()
        stale = (now - self._last_fetch_monotonic) > self.cache_ttl_seconds
        if self._cached_for_date != today or stale:
            self._cached_result = self._check(today)
            self._cached_for_date = today
            self._last_fetch_monotonic = now
        return self._cached_result

    def _check(self, today: date) -> bool:
        try:
            from src.data.providers.yfinance_provider import YFinanceProvider

            df = YFinanceProvider().get_ohlcv(_TAIEX_SYMBOL, "1m")
            if df.empty:
                logger.warning("No intraday TAIEX data at all -- assuming no confirmed closure today")
                return False
            last_bar_date = _to_taipei_date(df.index[-1])
        except Exception as exc:
            logger.warning("TAIEX intraday fetch failed, assuming no confirmed closure today: %s", exc)
            return False
        closed = last_bar_date < today
        if closed:
            logger.info("No intraday TAIEX bar for %s (last bar: %s) -- treating as market-closed", today, last_bar_date)
        return closed


def _to_taipei_date(ts) -> date:
    """yfinance's intraday index is typically tz-aware in the exchange's
    local timezone already; handle a naive timestamp defensively too
    rather than assuming one or the other."""
    py_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    if py_dt.tzinfo is None:
        return py_dt.date()
    return py_dt.astimezone(_TAIPEI).date()
