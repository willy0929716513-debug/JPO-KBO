"""Per-asset-class market-hours detection, so the pipeline only re-analyzes
symbols whose market is actually open right now instead of blindly
re-running everything on a fixed UTC window (which, e.g., completely missed
Taiwan's trading session in the original schedule).

Deliberately self-contained (uses only the stdlib `zoneinfo`, no extra
dependency like `pandas_market_calendars`) -- it approximates each market's
*regular weekly* trading hours correctly, including daylight-saving shifts
for US markets, but does NOT account for public holidays. A holiday will be
treated as a normal trading day and the symbol will simply be re-analyzed
against unchanged data, which is harmless (just a wasted, but cheap, no-op
run) rather than something that produces wrong output.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_US_EASTERN = ZoneInfo("America/New_York")
_TAIPEI = ZoneInfo("Asia/Taipei")

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
    return 9 * 60 <= minutes < 13 * 60 + 30  # 09:00-13:30 Asia/Taipei


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
