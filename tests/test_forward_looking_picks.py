from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import src.pipeline.daily_run as daily_run
from src.pipeline.daily_run import _get_forward_looking_picks


def _results_with_news():
    return [
        {"symbol": "2330.TW", "news": [{"title": "TSMC Sales Surge"}]},
        {"symbol": "2454.TW", "news": []},
    ]


def _outcome(status="ok", picks=None, detail=None):
    return {"status": status, "picks": picks or [], "detail": detail}


def test_generates_fresh_picks_when_no_previous_payload():
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               return_value=_outcome(picks=[{"symbol": "2454.TW", "reasoning": "supply chain"}])) as mock_predict:
        result = _get_forward_looking_picks(_results_with_news(), {})
    mock_predict.assert_called_once()
    assert result["picks"] == [{"symbol": "2454.TW", "reasoning": "supply chain"}]
    assert result["status"] == "ok"
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
        "generated_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
        "picks": [{"symbol": "2454.TW", "reasoning": "stale"}],
    }
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               return_value=_outcome(picks=[{"symbol": "2330.TW", "reasoning": "fresh"}])) as mock_predict:
        result = _get_forward_looking_picks(_results_with_news(), {"forward_looking_picks": stale})
    mock_predict.assert_called_once()
    assert result["picks"] == [{"symbol": "2330.TW", "reasoning": "fresh"}]


def test_regenerates_when_previous_timestamp_is_unparseable():
    malformed = {"generated_at": "not-a-real-timestamp", "picks": []}
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               return_value=_outcome()) as mock_predict:
        _get_forward_looking_picks(_results_with_news(), {"forward_looking_picks": malformed})
    mock_predict.assert_called_once()


def test_falls_back_to_previous_result_on_generation_failure():
    previous = {
        "generated_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
        "picks": [{"symbol": "2454.TW", "reasoning": "last known good"}],
    }
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               side_effect=RuntimeError("boom")):
        result = _get_forward_looking_picks(_results_with_news(), {"forward_looking_picks": previous})
    assert result == previous  # never raises, never wipes out the last known-good picks


def test_never_breaks_the_pipeline_with_no_prior_data_and_no_news():
    result = _get_forward_looking_picks([], {})
    assert result["picks"] == []


def test_key_configured_diagnostic_reflects_whether_a_key_is_set(monkeypatch):
    # Non-secret diagnostic (true/false only) so "no key configured" can be
    # told apart from "key configured but Gemini found nothing this cycle" --
    # both otherwise look identical (0 picks) from the outside.
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               return_value=_outcome()):
        result = _get_forward_looking_picks(_results_with_news(), {})
    assert result["key_configured"] is True


def test_key_configured_diagnostic_is_false_without_a_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               return_value=_outcome()):
        result = _get_forward_looking_picks(_results_with_news(), {})
    assert result["key_configured"] is False


def test_status_reflects_ok_with_empty_picks_when_gemini_finds_nothing(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               return_value=_outcome(status="ok", picks=[])):
        result = _get_forward_looking_picks(_results_with_news(), {})
    assert result["status"] == "ok"
    assert result["picks"] == []


def test_status_reflects_error_when_the_gemini_call_itself_fails(monkeypatch):
    # Distinct from "ok" + empty picks -- this is the case a user asked to
    # be able to tell apart: "AI genuinely found nothing" vs. "the call
    # itself broke" (bad response, quota, etc.), which otherwise both show
    # up identically as 0 picks on the dashboard.
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    with patch("src.data.providers.llm_provider.GeminiProvider.predict_future_beneficiaries",
               return_value=_outcome(status="error", detail="HTTP 429")):
        result = _get_forward_looking_picks(_results_with_news(), {})
    assert result["status"] == "error"
    assert result["picks"] == []
    assert result["detail"] == "HTTP 429"  # already-sanitized by llm_provider.py, safe to persist
