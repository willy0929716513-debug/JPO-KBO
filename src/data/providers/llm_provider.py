"""Forward-looking "which stock might benefit later" reasoning over the news
already collected across the whole watchlist, via Google Gemini's free API
tier (https://aistudio.google.com/apikey -- no credit card required).

Per user request: "不要按照現在新聞的趨勢走...根據你收集到的資訊去做判斷"
(don't just follow a stock's own current news trend -- reason from the
information collected). The keyword-based tagging in news_scoring.py only
ever answers "is THIS symbol's own headline positive or negative" -- it
can't notice that, say, a supply-chain partner's demand-surge headline
might make an upstream/downstream symbol a future beneficiary before that
symbol's own news catches up. That kind of cross-symbol inference needs
actual language understanding, which is exactly what an LLM does and a
keyword list cannot.

Requires a free `GEMINI_API_KEY` (https://aistudio.google.com/apikey).
Best-effort like every other optional-API-key integration in this project
(FRED_API_KEY, DISCORD_WEBHOOK_URL, etc.): with no key configured, or on
any failure (network error, rate limit, malformed response), this returns
an empty list rather than raising -- the pipeline must never break because
an optional AI feature isn't configured or is temporarily unavailable.

This repo's sandbox has no general internet access to test a real call
against Gemini's live API before shipping (see taiwan_holiday_provider.py
for the same caveat, and a case where an unverified endpoint silently
didn't work in production) -- but Gemini's REST API shape is a stable,
widely-documented public contract (unlike TWSE's undocumented internal
endpoint), so this is a meaningfully more reliable bet. Response parsing
is still defensive: any deviation from the expected shape is treated as
"no predictions this cycle", never a crash.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# 2026-07: was "gemini-2.0-flash", which Google fully shut down 2026-06-01.
# Persistent HTTP 429s that survived cutting call frequency to once/day (see
# FORWARD_LOOKING_PICKS_TTL_SECONDS in daily_run.py) were mistaken for a
# quota/rate-limit problem for weeks -- most likely explanation in hindsight
# is calls to the retired model itself being throttled/rejected, not a
# legitimate quota being exhausted by once-a-day traffic.
# gemini-2.5-flash-lite is Google's current free-tier model
# with the most generous quota (1,000 requests/day vs. 250 for plain
# gemini-2.5-flash) and no announced shutdown date as of this writing --
# see https://ai.google.dev/gemini-api/docs/deprecations before assuming a
# future 429 here is a quota issue rather than another silent retirement.
_GEMINI_MODEL = "gemini-2.5-flash-lite"
_GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_GEMINI_MODEL}:generateContent"
_MAX_HEADLINES_PER_SYMBOL = 3
_MAX_PICKS = 5

_PROMPT_TEMPLATE = """你是一位分析台股與美股新聞的助理。以下是目前追蹤清單裡各檔標的最近抓到的新聞標題。

任務：不要只看某檔標的「自己」的新聞有沒有利多——請找出「因為其他標的/產業的新聞內容，未來可能受惠」的
標的（例如上下游供應鏈、同產業技術/需求趨勢外溢效應），即使那檔標的自己目前還沒有相關新聞。只能從下面
「追蹤清單」裡的代碼中挑選，不能自己編造清單以外的代碼。最多挑 {max_picks} 檔，每檔請附上具體推論理由，
並註明是根據追蹤清單裡哪一則新聞標題做的推論。如果找不到有把握的推論，回傳空陣列即可，不要勉強湊數。

追蹤清單與最近新聞：
{news_summary}

請只回傳這個 JSON 格式，不要有其他文字：
{{"picks": [{{"symbol": "追蹤清單裡的代碼", "reasoning": "推論理由（繁體中文）", "based_on_symbol": "推論依據的標的代碼", "based_on_headline": "推論依據的新聞標題"}}]}}
"""


def _build_news_summary(news_by_symbol: dict[str, list[dict]]) -> str:
    lines = []
    for symbol, news in news_by_symbol.items():
        if not news:
            continue
        titles = [n.get("title", "") for n in news[:_MAX_HEADLINES_PER_SYMBOL] if n.get("title")]
        if titles:
            lines.append(f"- {symbol}: " + " / ".join(titles))
    return "\n".join(lines)


class GeminiProvider:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def predict_future_beneficiaries(self, news_by_symbol: dict[str, list[dict]],
                                      valid_symbols: set[str]) -> dict:
        """Returns {"status": "no_key"|"no_news"|"error"|"ok", "picks": [...],
        "detail": str|None}. "ok" with an empty picks list means the call
        genuinely succeeded and Gemini found nothing confident to report --
        deliberately kept distinct from "error" (network failure, bad
        response, unparseable JSON), since both would otherwise show up as
        "0 picks" on the dashboard with no way to tell them apart."""
        if not self.api_key:
            logger.info("GEMINI_API_KEY not set; skipping AI forward-looking picks")
            return {"status": "no_key", "picks": [], "detail": None}
        news_summary = _build_news_summary(news_by_symbol)
        if not news_summary:
            return {"status": "no_news", "picks": [], "detail": None}
        prompt = _PROMPT_TEMPLATE.format(max_picks=_MAX_PICKS, news_summary=news_summary)
        try:
            raw_text = self._call_gemini(prompt)
        except Exception as exc:
            detail = _safe_error_detail(exc)
            logger.warning("Gemini API call failed: %s", detail)
            return {"status": "error", "picks": [], "detail": detail}
        picks = _parse_picks(raw_text, valid_symbols)
        if picks is None:
            return {"status": "error", "picks": [], "detail": "Gemini response wasn't in the expected format"}
        return {"status": "ok", "picks": picks[:_MAX_PICKS], "detail": None}

    def _call_gemini(self, prompt: str) -> str:
        import requests

        # The key goes in a header, never the URL/query string -- requests'
        # own exception messages (e.g. HTTPError) include the full request
        # URL, and this repo's `detail` field ends up in the *public*
        # signals_latest.json on GitHub Pages. A `?key=...` query parameter
        # would have leaked the live API key into that public file the
        # moment a call ever failed.
        resp = requests.post(
            _GEMINI_URL,
            headers={"x-goog-api-key": self.api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


def _safe_error_detail(exc: Exception) -> str:
    """A short, safe-to-publish description of a failed Gemini call --
    deliberately NOT `str(exc)`. requests' own exceptions (HTTPError,
    ConnectionError, etc.) routinely embed the full request URL in their
    message, which would otherwise carry the key through to _call_gemini's
    caller even with the header-based auth fix above (e.g. a proxy or
    redirect could still surface it in some requests versions) -- this
    stays limited to the exception type and, for an HTTP error, its status
    code, both safe to display and to persist in the public
    signals_latest.json."""
    import requests

    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def _parse_picks(raw_text: str, valid_symbols: set[str]) -> list[dict] | None:
    """Returns None (a distinct "error" sentinel, not just an empty list) if
    the response wasn't structurally the JSON shape asked for -- as opposed
    to a valid-but-empty `{"picks": []}`, which legitimately means Gemini
    looked and found nothing confident. A pick that gets filtered out below
    (hallucinated symbol, missing reasoning) doesn't count as a structural
    failure by itself; only a genuinely malformed/wrong-shaped response does."""
    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Gemini response wasn't valid JSON, discarding this cycle's picks")
        return None
    picks = parsed.get("picks") if isinstance(parsed, dict) else None
    if not isinstance(picks, list):
        logger.warning("Gemini response didn't have the expected {\"picks\": [...]} shape")
        return None

    result = []
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        symbol = pick.get("symbol")
        reasoning = pick.get("reasoning")
        if symbol not in valid_symbols or not reasoning:
            continue  # never surface a hallucinated ticker outside the real watchlist
        result.append({
            "symbol": symbol,
            "reasoning": str(reasoning),
            "based_on_symbol": pick.get("based_on_symbol"),
            "based_on_headline": pick.get("based_on_headline"),
        })
    return result
