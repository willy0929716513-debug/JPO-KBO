from datetime import datetime, timezone

import pytest

import src.data.market_hours as market_hours
from src.data.market_hours import is_market_open


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _stub_taiwan_holiday_provider(monkeypatch):
    # Every test in this file should exercise the weekday+clock heuristic in
    # isolation, offline -- TaiwanHolidayProvider.is_closed_today() does a
    # real network call otherwise. Individual tests override this via
    # monkeypatch when they specifically want to simulate an ad-hoc closure.
    monkeypatch.setattr(market_hours._taiwan_holiday_provider, "is_closed_today", lambda today=None: False)


def test_crypto_always_open():
    assert is_market_open("crypto", _utc(2026, 7, 4, 3, 0)) is True  # Saturday 3am UTC
    assert is_market_open("crypto", _utc(2026, 7, 6, 14, 0)) is True  # Monday


def test_us_equity_open_during_regular_session():
    # 2026-07-06 is a Monday. 14:30 UTC = 10:30am ET (assuming EDT, UTC-4 in July).
    assert is_market_open("equity", _utc(2026, 7, 6, 14, 30)) is True
    assert is_market_open("etf", _utc(2026, 7, 6, 14, 30)) is True


def test_us_equity_closed_outside_session():
    # 03:00 UTC on a Tuesday is the middle of the US night -- market closed.
    assert is_market_open("equity", _utc(2026, 7, 7, 3, 0)) is False


def test_us_equity_closed_on_weekend():
    # 2026-07-04 is a Saturday.
    assert is_market_open("equity", _utc(2026, 7, 4, 15, 0)) is False


def test_taiwan_equity_open_during_session():
    # 02:00 UTC = 10:00am Asia/Taipei (UTC+8, no DST) on a Monday.
    assert is_market_open("taiwan", _utc(2026, 7, 6, 2, 0)) is True


def test_taiwan_equity_closed_outside_session():
    # 06:00 UTC = 2:00pm Asia/Taipei -- after the 13:30 close.
    assert is_market_open("taiwan", _utc(2026, 7, 6, 6, 0)) is False


def test_taiwan_equity_closed_on_ad_hoc_closure_during_normal_hours(monkeypatch):
    # Regression test for a real user report: TWSE was closed 2026-07-10
    # (an ordinary Friday) for Typhoon Bawi, but the plain weekday+clock
    # heuristic alone would have said "open" during 09:00-13:30. When
    # TaiwanHolidayProvider confirms an ad-hoc closure, is_market_open must
    # report closed even though it's a weekday within regular hours.
    monkeypatch.setattr(market_hours._taiwan_holiday_provider, "is_closed_today", lambda today=None: True)
    # 02:00 UTC = 10:00am Asia/Taipei on a Friday -- squarely within normal hours.
    assert is_market_open("taiwan", _utc(2026, 7, 10, 2, 0)) is False


def test_taiwan_equity_not_affected_by_ad_hoc_closure_check_outside_hours(monkeypatch):
    # The ad-hoc closure check should only even be consulted when the
    # weekday+clock heuristic would otherwise say "open" -- no need to
    # short-circuit differently outside trading hours, but this locks in
    # that behavior doesn't regress either way.
    calls = []

    def _tracking_is_closed_today(today=None):
        calls.append(today)
        return False

    monkeypatch.setattr(market_hours._taiwan_holiday_provider, "is_closed_today", _tracking_is_closed_today)
    assert is_market_open("taiwan", _utc(2026, 7, 6, 6, 0)) is False  # after close
    assert calls == []  # never consulted once already closed by the clock


def test_forex_and_futures_open_on_weekday():
    assert is_market_open("forex", _utc(2026, 7, 8, 12, 0)) is True  # Wednesday
    assert is_market_open("metal", _utc(2026, 7, 8, 12, 0)) is True
    assert is_market_open("energy", _utc(2026, 7, 8, 12, 0)) is True


def test_forex_closed_on_saturday():
    assert is_market_open("forex", _utc(2026, 7, 4, 12, 0)) is False  # Saturday


def test_forex_closed_early_sunday_opens_late_sunday():
    assert is_market_open("forex", _utc(2026, 7, 5, 10, 0)) is False   # Sunday morning UTC
    assert is_market_open("forex", _utc(2026, 7, 5, 23, 0)) is True    # Sunday night UTC, after reopen


def test_forex_closes_friday_evening():
    assert is_market_open("forex", _utc(2026, 7, 10, 12, 0)) is True   # Friday midday
    assert is_market_open("forex", _utc(2026, 7, 10, 23, 0)) is False  # Friday night, after close


def test_unknown_asset_class_defaults_open():
    assert is_market_open("something_new") is True
