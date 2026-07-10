from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.data.providers.taiwan_holiday_provider import TaiwanHolidayProvider, _to_taipei_date

_TAIPEI = ZoneInfo("Asia/Taipei")

# Deliberately not 2026-07-10 (today, per this repo's sandbox clock) --
# using a fixed past date for most tests avoids any interaction with the
# grace-period check, which only kicks in when `today` matches the real
# current date.
_PAST_DATE = date(2024, 1, 1)


def _df_with_last_bar(ts) -> pd.DataFrame:
    return pd.DataFrame({"close": [123.0]}, index=pd.DatetimeIndex([ts]))


def test_to_taipei_date_handles_tz_aware_timestamp():
    ts = pd.Timestamp("2026-07-10 09:05:00", tz="Asia/Taipei")
    assert _to_taipei_date(ts) == date(2026, 7, 10)


def test_to_taipei_date_converts_across_timezones():
    ts = pd.Timestamp("2026-07-10 01:05:00", tz="UTC")  # 09:05 Taipei
    assert _to_taipei_date(ts) == date(2026, 7, 10)


def test_to_taipei_date_handles_naive_timestamp():
    ts = pd.Timestamp("2026-07-10 09:05:00")
    assert _to_taipei_date(ts) == date(2026, 7, 10)


def test_check_returns_closed_when_no_intraday_bar_posted_today():
    provider = TaiwanHolidayProvider()
    stale_df = _df_with_last_bar(pd.Timestamp("2026-07-09 13:29:00", tz="Asia/Taipei"))
    with patch("src.data.providers.yfinance_provider.YFinanceProvider.get_ohlcv", return_value=stale_df):
        assert provider._check(date(2026, 7, 10)) is True


def test_check_returns_open_when_todays_intraday_bar_exists():
    provider = TaiwanHolidayProvider()
    fresh_df = _df_with_last_bar(pd.Timestamp("2026-07-10 09:05:00", tz="Asia/Taipei"))
    with patch("src.data.providers.yfinance_provider.YFinanceProvider.get_ohlcv", return_value=fresh_df):
        assert provider._check(date(2026, 7, 10)) is False


def test_check_fails_safe_open_on_empty_data():
    provider = TaiwanHolidayProvider()
    with patch("src.data.providers.yfinance_provider.YFinanceProvider.get_ohlcv", return_value=pd.DataFrame()):
        assert provider._check(date(2026, 7, 10)) is False


def test_check_fails_safe_open_on_exception():
    provider = TaiwanHolidayProvider()
    with patch("src.data.providers.yfinance_provider.YFinanceProvider.get_ohlcv", side_effect=ConnectionError("blocked")):
        assert provider._check(date(2026, 7, 10)) is False


def test_is_closed_today_reflects_check_result():
    provider = TaiwanHolidayProvider()
    with patch.object(TaiwanHolidayProvider, "_check", return_value=True):
        assert provider.is_closed_today(_PAST_DATE) is True


def test_is_closed_today_caches_within_ttl_for_same_date():
    provider = TaiwanHolidayProvider(cache_ttl_seconds=3600)
    with patch.object(TaiwanHolidayProvider, "_check", return_value=False) as mock_check:
        provider.is_closed_today(_PAST_DATE)
        provider.is_closed_today(_PAST_DATE)
        assert mock_check.call_count == 1


def test_is_closed_today_rechecks_for_a_new_date():
    provider = TaiwanHolidayProvider(cache_ttl_seconds=3600)
    with patch.object(TaiwanHolidayProvider, "_check", return_value=False) as mock_check:
        provider.is_closed_today(_PAST_DATE)
        provider.is_closed_today(date(2024, 1, 2))
        assert mock_check.call_count == 2


def test_is_closed_today_grace_period_assumes_open_right_after_open_bell():
    # Regression guard: checking too close to the 09:00 open on a
    # genuinely-open day could look identical to a closed one, since
    # yfinance's intraday feed isn't instantaneous. Within the grace
    # window, _check must not even be consulted.
    provider = TaiwanHolidayProvider()
    fake_now = datetime(2026, 7, 10, 9, 5, tzinfo=_TAIPEI)  # 5 minutes after open
    with patch("src.data.providers.taiwan_holiday_provider.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        with patch.object(TaiwanHolidayProvider, "_check") as mock_check:
            assert provider.is_closed_today(date(2026, 7, 10)) is False
            mock_check.assert_not_called()


def test_is_closed_today_consults_check_after_grace_period():
    provider = TaiwanHolidayProvider()
    fake_now = datetime(2026, 7, 10, 9, 20, tzinfo=_TAIPEI)  # past the 15-minute grace window
    with patch("src.data.providers.taiwan_holiday_provider.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        with patch.object(TaiwanHolidayProvider, "_check", return_value=True) as mock_check:
            assert provider.is_closed_today(date(2026, 7, 10)) is True
            mock_check.assert_called_once()
