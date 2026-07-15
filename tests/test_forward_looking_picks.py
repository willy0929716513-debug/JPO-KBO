from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import src.pipeline.daily_run as daily_run
from src.pipeline.daily_run import _get_forward_looking_picks


def _results_with_news():
    return [
        {"symbol": "2330.TW", "news": [{"title": "TSMC Sales Surge"}]},
        {"symbol": "2454.TW", "news": []},
    ]


def test_generates_fresh_picks_when_no_previous_payload():
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               return_value=[{"symbol": "2454.TW", "reasoning": "supply chain"}]) as mock_predict:
        result = _get_forward_looking_picks(_results_with_news(), {})
    mock_predict.assert_called_once()
    assert result["picks"] == [{"symbol": "2454.TW", "reasoning": "supply chain"}]
    assert "generated_at" in result


def test_reuses_recent_previous_picks_without_calling_the_api():
    recent = {
        "generated_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "picks": [{"symbol": "2454.TW", "reasoning": "old but still fresh"}],
    }
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries") as mock_predict:
        result = _get_forward_looking_picks(_results_with_news(), {"forward_looking_picks": recent})
    mock_predict.assert_not_called()
    assert result == recent


def test_regenerates_when_previous_picks_are_stale():
    stale = {
        "generated_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "picks": [{"symbol": "2454.TW", "reasoning": "stale"}],
    }
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               return_value=[{"symbol": "2330.TW", "reasoning": "fresh"}]) as mock_predict:
        result = _get_forward_looking_picks(_results_with_news(), {"forward_looking_picks": stale})
    mock_predict.assert_called_once()
    assert result["picks"] == [{"symbol": "2330.TW", "reasoning": "fresh"}]


def test_regenerates_when_previous_timestamp_is_unparseable():
    malformed = {"generated_at": "not-a-real-timestamp", "picks": []}
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               return_value=[]) as mock_predict:
        _get_forward_looking_picks(_results_with_news(), {"forward_looking_picks": malformed})
    mock_predict.assert_called_once()


def test_falls_back_to_previous_result_on_generation_failure():
    previous = {
        "generated_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "picks": [{"symbol": "2454.TW", "reasoning": "last known good"}],
    }
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               side_effect=RuntimeError("boom")):
        result = _get_forward_looking_picks(_results_with_news(), {"forward_looking_picks": previous})
    assert result == previous  # never raises, never wipes out the last known-good picks


def test_never_breaks_the_pipeline_with_no_prior_data_and_no_news():
    result = _get_forward_looking_picks([], {})
    assert result["picks"] == []
