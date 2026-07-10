"""Per-asset-class market-hours detection, so the pipeline only re-analyzes
symbols whose market is actually open right now instead of blindly
re-running everything on a fixed UTC window (which, e.g., completely missed
Taiwan's trading session in the original schedule).

Mostly self-contained (uses only the stdlib `zoneinfo`, no extra dependency
like `pandas_market_calendars`) -- it approximates each market's *regular
weekly* trading hours correctly, including daylight-saving shifts for US
markets, but a fixed weekday+clock rule can never know about a public
holiday, let alone an ad-hoc same-day closure (e.g. Taiwan's "颱風假"
typhoon days -- announced the morning of based on weather, impossible to
encode in any static calendar in advance; real user report on 2026-07-10:
TWSE was closed for Typhoon Bawi on an ordinary weekday, and this module
still said "open"). For Taiwan specifically, an additional best-effort live
check (TaiwanHolidayProvider) narrows a weekday-hours "open" verdict down
to "closed" if TWSE's own published schedule confirms today is a closure --
see that module's docstring for why it's built to fail safely closed-to-the-
existing-behavior (i.e. never invents a false closure) rather than assert
a guessed API shape confidently. For every other asset class, an
undetected holiday just means the symbol gets harmlessly re-analyzed
against unchanged data (a wasted but cheap no-op run), same as before.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.data.providers.taiwan_holiday_provider import TaiwanHolidayProvider

logger = logging.getLogger(__name__)

_US_EASTERN = ZoneInfo("America/New_York")
_TAIPEI = ZoneInfo("Asia/Taipei")
_taiwan_holiday_provider = TaiwanHolidayProvider()

# Asset classes that are effectively open around the clock on weekdays (forex
# and CME/COMEX-style futures both run roughly Sun 5pm ET -> Fri 5pm ET with
# only brief daily maintenance breaks that aren't worth modeling at 5-minute
# granularity).
_NEAR_24H_CLASSES = {"forex", "metal", "energy"}


def _now(now: datetime | None) -> datetime:
    return now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)


def _is_us_equity_hours(now_utc: datetime) -> bool:
    local = now_utc.astimezone(_US_EASTERN)
    if local.weekday() >= 5:  # Saturday/Sunday
        return False
    minutes = local.hour * 60 + local.minute
    return 9 * 60 + 30 <= minutes < 16 * 60  # 09:30-16:00 America/New_York


def _is_taiwan_equity_hours(now_utc: datetime) -> bool:
    local = now_utc.astimezone(_TAIPEI)
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    if not (9 * 60 <= minutes < 13 * 60 + 30):  # 09:00-13:30 Asia/Taipei
        return False
    if _taiwan_holiday_provider.is_closed_today(local.date()):
        logger.info("TWSE ad-hoc closure detected for %s -- treating as market-closed", local.date())
        return False
    return True


def _is_near_24h_open(now_utc: datetime) -> bool:
    """Sun 22:00 UTC (~5pm ET, DST-approximate) through Fri 22:00 UTC, closed
    the rest of the weekend. Good enough at 5-minute granularity."""
    weekday, minutes = now_utc.weekday(), now_utc.hour * 60 + now_utc.minute
    if weekday == 5:  # Saturday: always closed
        return False
    if weekday == 6:  # Sunday: opens at 22:00 UTC
        return minutes >= 22 * 60
    if weekday == 4:  # Friday: closes at 22:00 UTC
        return minutes < 22 * 60
    return True  # Mon-Thu


def is_market_open(asset_class: str, now: datetime | None = None) -> bool:
    """Returns whether `asset_class`'s market is currently in its regular
    trading session. Unknown asset classes default to True (analyze it
    rather than silently skip something we don't have a rule for)."""
    now_utc = _now(now)

    if asset_class == "crypto":
        return True
    if asset_class == "taiwan":
        return _is_taiwan_equity_hours(now_utc)
    if asset_class in ("equity", "etf"):
        return _is_us_equity_hours(now_utc)
    if asset_class in _NEAR_24H_CLASSES:
        return _is_near_24h_open(now_utc)
    return True
