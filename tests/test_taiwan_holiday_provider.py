from datetime import date
from unittest.mock import patch

from src.data.providers.taiwan_holiday_provider import TaiwanHolidayProvider, _text_marks_date_closed


def test_text_marks_date_closed_detects_gregorian_date_with_keyword():
    text = "2026/07/10,五,颱風巴威來襲，台股全日休市"
    assert _text_marks_date_closed(text, date(2026, 7, 10)) is True


def test_text_marks_date_closed_detects_roc_calendar_date():
    text = "115/07/10,五,休市"
    assert _text_marks_date_closed(text, date(2026, 7, 10)) is True


def test_text_marks_date_closed_ignores_unrelated_dates():
    text = "2026/07/09,四,正常交易\n2026/07/11,六,週末非交易日"
    assert _text_marks_date_closed(text, date(2026, 7, 10)) is False


def test_text_marks_date_closed_requires_both_date_and_keyword_on_same_line():
    # The date appears, but with no closure keyword on that line -- a normal
    # trading day shouldn't be misread as closed just because its date is
    # mentioned somewhere in the schedule (e.g. a "next trading day" note).
    text = "2026/07/10,五,正常交易"
    assert _text_marks_date_closed(text, date(2026, 7, 10)) is False


def test_text_marks_date_closed_handles_empty_text():
    assert _text_marks_date_closed("", date(2026, 7, 10)) is False


def test_is_closed_today_returns_false_on_fetch_failure():
    provider = TaiwanHolidayProvider()
    with patch("requests.get", side_effect=ConnectionError("blocked")):
        assert provider.is_closed_today(date(2026, 7, 10)) is False


def test_is_closed_today_reflects_check_result():
    provider = TaiwanHolidayProvider()
    with patch.object(TaiwanHolidayProvider, "_check", return_value=True):
        assert provider.is_closed_today(date(2026, 7, 10)) is True


def test_is_closed_today_caches_within_ttl_for_same_date():
    provider = TaiwanHolidayProvider(cache_ttl_seconds=3600)
    with patch.object(TaiwanHolidayProvider, "_check", return_value=False) as mock_check:
        provider.is_closed_today(date(2026, 7, 10))
        provider.is_closed_today(date(2026, 7, 10))
        assert mock_check.call_count == 1


def test_is_closed_today_rechecks_for_a_new_date():
    provider = TaiwanHolidayProvider(cache_ttl_seconds=3600)
    with patch.object(TaiwanHolidayProvider, "_check", return_value=False) as mock_check:
        provider.is_closed_today(date(2026, 7, 10))
        provider.is_closed_today(date(2026, 7, 11))
        assert mock_check.call_count == 2
