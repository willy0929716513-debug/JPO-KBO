import json
from unittest.mock import MagicMock, patch

from src.data.providers.llm_provider import GeminiProvider, _build_news_summary, _parse_picks


def _news(*titles):
    return [{"title": t} for t in titles]


def test_build_news_summary_skips_symbols_with_no_news():
    news_by_symbol = {"2330.TW": _news("TSMC Sales Surge"), "2317.TW": []}
    summary = _build_news_summary(news_by_symbol)
    assert "2330.TW" in summary
    assert "2317.TW" not in summary


def test_build_news_summary_caps_headlines_per_symbol():
    news_by_symbol = {"2330.TW": _news("A", "B", "C", "D", "E")}
    summary = _build_news_summary(news_by_symbol)
    assert "A" in summary and "B" in summary and "C" in summary
    assert "D" not in summary and "E" not in summary


def test_predict_returns_no_key_status_without_api_key():
    provider = GeminiProvider(api_key=None)
    result = provider.predict_future_beneficiaries({"2330.TW": _news("TSMC Sales Surge")}, {"2330.TW"})
    assert result == {"status": "no_key", "picks": [], "detail": None}


def test_predict_returns_no_news_status_when_no_usable_news():
    provider = GeminiProvider(api_key="fake-key")
    result = provider.predict_future_beneficiaries({"2330.TW": []}, {"2330.TW"})
    assert result == {"status": "no_news", "picks": [], "detail": None}


def test_predict_returns_ok_status_with_parsed_picks_on_success():
    provider = GeminiProvider(api_key="fake-key")
    fake_response_text = json.dumps({
        "picks": [{"symbol": "2454.TW", "reasoning": "供應鏈受惠", "based_on_symbol": "2330.TW",
                    "based_on_headline": "TSMC Sales Surge"}]
    })
    with patch.object(GeminiProvider, "_call_gemini", return_value=fake_response_text):
        result = provider.predict_future_beneficiaries(
            {"2330.TW": _news("TSMC Sales Surge"), "2454.TW": []},
            {"2330.TW", "2454.TW"},
        )
    assert result["status"] == "ok"
    assert result["picks"] == [{
        "symbol": "2454.TW", "reasoning": "供應鏈受惠",
        "based_on_symbol": "2330.TW", "based_on_headline": "TSMC Sales Surge",
    }]


def test_predict_returns_ok_status_with_empty_picks_when_gemini_finds_nothing():
    # Distinct from "error": the call succeeded and Gemini legitimately
    # decided there was nothing confident to report this cycle.
    provider = GeminiProvider(api_key="fake-key")
    with patch.object(GeminiProvider, "_call_gemini", return_value=json.dumps({"picks": []})):
        result = provider.predict_future_beneficiaries({"2330.TW": _news("x")}, {"2330.TW"})
    assert result == {"status": "ok", "picks": [], "detail": None}


def test_predict_returns_error_status_on_network_error():
    provider = GeminiProvider(api_key="fake-key")
    with patch.object(GeminiProvider, "_call_gemini", side_effect=ConnectionError("blocked")):
        result = provider.predict_future_beneficiaries({"2330.TW": _news("x")}, {"2330.TW"})
    assert result["status"] == "error"
    assert result["picks"] == []
    assert "blocked" in result["detail"]


def test_predict_returns_error_status_on_unparseable_response():
    provider = GeminiProvider(api_key="fake-key")
    with patch.object(GeminiProvider, "_call_gemini", return_value="not json at all"):
        result = provider.predict_future_beneficiaries({"2330.TW": _news("x")}, {"2330.TW"})
    assert result["status"] == "error"
    assert result["picks"] == []


def test_call_gemini_sends_expected_request_shape():
    provider = GeminiProvider(api_key="fake-key")
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
    with patch("requests.post", return_value=fake_resp) as mock_post:
        text = provider._call_gemini("hello")
    assert text == "{}"
    _, kwargs = mock_post.call_args
    assert kwargs["params"]["key"] == "fake-key"
    assert kwargs["json"]["contents"][0]["parts"][0]["text"] == "hello"


def test_parse_picks_discards_hallucinated_symbol_outside_watchlist():
    raw = json.dumps({"picks": [{"symbol": "FAKE.TW", "reasoning": "made up"}]})
    assert _parse_picks(raw, {"2330.TW"}) == []  # structurally valid, just nothing survives


def test_parse_picks_discards_pick_missing_reasoning():
    raw = json.dumps({"picks": [{"symbol": "2330.TW"}]})
    assert _parse_picks(raw, {"2330.TW"}) == []


def test_parse_picks_returns_none_on_malformed_json():
    assert _parse_picks("not json at all", {"2330.TW"}) is None


def test_parse_picks_returns_none_on_unexpected_shape():
    assert _parse_picks(json.dumps({"picks": "not a list"}), {"2330.TW"}) is None
    assert _parse_picks(json.dumps({"something_else": []}), {"2330.TW"}) is None
    assert _parse_picks(json.dumps(["a", "list", "not", "a", "dict"]), {"2330.TW"}) is None


def test_parse_picks_returns_empty_list_not_none_when_structurally_valid_but_empty():
    assert _parse_picks(json.dumps({"picks": []}), {"2330.TW"}) == []
