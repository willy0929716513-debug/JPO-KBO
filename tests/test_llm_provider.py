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
    with patch.object(GeminiProvider, "_call_gemini", side_effect=ConnectionError("blocked: https://x/?key=super-secret")):
        result = provider.predict_future_beneficiaries({"2330.TW": _news("x")}, {"2330.TW"})
    assert result["status"] == "error"
    assert result["picks"] == []
    # detail must never leak the raw exception text (which could embed the
    # request URL/key) -- only a safe, generic classification.
    assert result["detail"] == "ConnectionError"
    assert "super-secret" not in result["detail"]


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
    assert kwargs["json"]["contents"][0]["parts"][0]["text"] == "hello"


def test_call_gemini_sends_key_via_header_not_query_string():
    # Regression guard: a `?key=...` query parameter would end up embedded
    # in requests' own exception messages (e.g. HTTPError includes the full
    # request URL) -- and this repo's error `detail` field is persisted in
    # the *public* signals_latest.json. The key must only ever travel via
    # a header, never a query parameter.
    provider = GeminiProvider(api_key="fake-key")
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
    with patch("requests.post", return_value=fake_resp) as mock_post:
        provider._call_gemini("hello")
    _, kwargs = mock_post.call_args
    assert "params" not in kwargs
    assert kwargs["headers"]["x-goog-api-key"] == "fake-key"


def test_safe_error_detail_never_includes_raw_exception_text():
    from src.data.providers.llm_provider import _safe_error_detail

    exc = ConnectionError("failed to connect to https://x/?key=super-secret-value")
    detail = _safe_error_detail(exc)
    assert "super-secret-value" not in detail
    assert detail == "ConnectionError"


def test_safe_error_detail_reports_http_status_without_leaking_url():
    from src.data.providers.llm_provider import _safe_error_detail
    import requests

    fake_response = MagicMock()
    fake_response.status_code = 429
    exc = requests.exceptions.HTTPError(
        "429 Client Error: Too Many Requests for url: https://x/?key=super-secret-value",
        response=fake_response,
    )
    detail = _safe_error_detail(exc)
    assert detail == "HTTP 429"
    assert "super-secret-value" not in detail


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


def test_parse_picks_strips_markdown_code_fence_around_otherwise_valid_json():
    """Regression test for a real production issue: after migrating to
    gemini-flash-lite-latest (see the model-migration comment above
    _GEMINI_MODEL), the AI forward-looking picks feature started failing
    with "Gemini response wasn't in the expected format" even though
    responseMimeType=application/json was requested -- some models wrap
    "JSON mode" output in a markdown code fence anyway, a long-documented
    quirk of LLM structured output in general, not specific to this
    provider. An otherwise-valid response shouldn't be discarded just
    because of the fence around it."""
    raw = "```json\n" + json.dumps({"picks": [{"symbol": "2330.TW", "reasoning": "x"}]}) + "\n```"
    assert _parse_picks(raw, {"2330.TW"}) == [
        {"symbol": "2330.TW", "reasoning": "x", "based_on_symbol": None, "based_on_headline": None}
    ]


def test_parse_picks_strips_code_fence_without_language_tag():
    raw = "```\n" + json.dumps({"picks": []}) + "\n```"
    assert _parse_picks(raw, {"2330.TW"}) == []


def test_call_gemini_logs_non_stop_finish_reason(caplog):
    """A finishReason other than STOP (e.g. MAX_TOKENS) means the response
    may have been cut off mid-JSON -- surfaced in server logs only (never
    the public signals_latest.json) so a truncated response can actually be
    diagnosed from a real production failure instead of guessed at, since
    this repo's sandbox has no way to call the live API directly."""
    provider = GeminiProvider(api_key="fake-key")
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"pi'}]}}]
    }
    with patch("requests.post", return_value=fake_resp), caplog.at_level("WARNING"):
        provider._call_gemini("hello")
    assert "MAX_TOKENS" in caplog.text


def test_parse_picks_logs_raw_response_snippet_on_malformed_json(caplog):
    with caplog.at_level("WARNING"):
        _parse_picks("not json at all", {"2330.TW"})
    assert "not json at all" in caplog.text


def test_call_gemini_joins_multiple_response_parts():
    """A response can legitimately come back split across more than one
    part -- indexing parts[0] alone would silently drop the rest instead of
    returning the complete text."""
    provider = GeminiProvider(api_key="fake-key")
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"pi'}, {"text": 'cks": []}'}]}}]
    }
    with patch("requests.post", return_value=fake_resp):
        text = provider._call_gemini("hello")
    assert text == '{"picks": []}'
