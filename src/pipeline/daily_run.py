"""The single orchestration entry point that ties every module together:

  fetch data -> build features -> detect regime -> run strategies -> combine
  into a final signal -> run a quick backtest snapshot -> run the multi-agent
  decision engine (technical + macro + risk) -> analyze a few correlated
  pairs for statistical arbitrage -> export everything as JSON for the
  GitHub Pages dashboard.

Run it with `python scripts/run_pipeline.py`. It's also what the daily
GitHub Actions workflow calls. Every network call is wrapped so a single
symbol failing (e.g. Yahoo Finance hiccup) never aborts the whole run.
"""
from __future__ import annotations

import json
import logging
import math
import traceback
from datetime import datetime, timezone

import pandas as pd

from src.agents import AgentContext, DecisionEngine, MacroAgent, RiskAgent, TechnicalAgent
from src.backtest.engine import BacktestEngine
from src.config import DOCS_DATA_DIR, settings
from src.data.market_hours import is_market_open
from src.data.news_scoring import score_news_batch
from src.data.providers.ccxt_provider import CCXTProvider
from src.data.providers.llm_provider import GeminiProvider
from src.data.providers.macro_provider import MacroProvider
from src.data.providers.sentiment_provider import SentimentProvider
from src.data.providers.yfinance_provider import YFinanceProvider
from src.features.feature_pipeline import FeaturePipeline
from src.pipeline import auto_trader
from src.regime.detector import RegimeDetector
from src.risk.limits import LossLimitMonitor
from src.risk.portfolio_risk import DrawdownCircuitBreaker, max_drawdown
from src.strategies import (
    BreakoutStrategy, MeanReversionStrategy, MomentumStrategy, PairsTradingStrategy,
    StrategyCombiner, TrendFollowingStrategy,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Curated default watchlist across every asset class the prompt asked for.
# Taiwan large-caps are the primary focus (listed first, and the widest
# single-market list) per user request; everything else is kept as a
# smaller supporting watchlist. Still kept small enough to run comfortably
# inside a GitHub Actions job on a 5-minute cron.
WATCHLIST = {
    "taiwan": [
        "2330.TW",  # 台積電
        "2317.TW",  # 鴻海
        "2454.TW",  # 聯發科
        "2308.TW",  # 台達電
        "2382.TW",  # 廣達
        "2303.TW",  # 聯電
        "2881.TW",  # 富邦金
        "2882.TW",  # 國泰金
        "2412.TW",  # 中華電
        "1301.TW",  # 台塑
        "2603.TW",  # 長榮
        "3711.TW",  # 日月光投控
        "0050.TW",  # 元大台灣50
        "2002.TW",  # 中鋼
        "1216.TW",  # 統一
        "2886.TW",  # 兆豐金
        "2891.TW",  # 中信金
        "2892.TW",  # 第一金
        "2884.TW",  # 玉山金
        "2885.TW",  # 元大金
        "2880.TW",  # 華南金
        "5880.TW",  # 合庫金
        "2887.TW",  # 台新金
        "2890.TW",  # 永豐金
        "1101.TW",  # 台泥
        "1303.TW",  # 南亞
        "1326.TW",  # 台化
        "2379.TW",  # 瑞昱
        "2357.TW",  # 華碩
        "2353.TW",  # 宏碁
        "2408.TW",  # 南亞科
        "2609.TW",  # 陽明
        "2615.TW",  # 萬海
        "3034.TW",  # 聯詠
        "3037.TW",  # 欣興
        "3045.TW",  # 台灣大
        "4904.TW",  # 遠傳
        "2207.TW",  # 和泰車
        "9910.TW",  # 豐泰
        "6505.TW",  # 台塑化
        "2395.TW",  # 研華
        "3008.TW",  # 大立光
        "2409.TW",  # 友達
        "3231.TW",  # 緯創
        "2324.TW",  # 仁寶
        "2327.TW",  # 國巨
        "5871.TW",  # 中租-KY
        "2377.TW",  # 微星
    ],
    "equity": ["AAPL", "MSFT", "NVDA", "TSLA"],
    "etf": ["SPY", "QQQ"],
    "metal": ["GC=F", "SI=F"],
    "energy": ["CL=F"],
    "forex": ["EURUSD=X"],
    "crypto": ["BTC/USDT", "ETH/USDT"],
}

# A few historically-related pairs to screen for statistical arbitrage
# opportunities. Cointegration is tested fresh every run -- a pair only
# generates a trade signal when it currently passes the test, not because
# it's hardcoded here.
PAIR_WATCHLIST = [("GC=F", "SI=F", "metal"), ("SPY", "QQQ", "etf"), ("BTC/USDT", "ETH/USDT", "crypto")]


def _asset_class_of(symbol: str) -> str:
    for cls, syms in WATCHLIST.items():
        if symbol in syms:
            return cls
    return "other"


def _load_ohlcv(symbol: str, asset_class: str, interval: str = "1d") -> pd.DataFrame:
    if asset_class == "crypto":
        return CCXTProvider().get_ohlcv(symbol, interval)
    return YFinanceProvider().get_ohlcv(symbol, interval)


def _load_news(symbol: str, asset_class: str) -> list[dict]:
    # No free, reliable news source wired up for crypto yet -- yfinance's
    # (free) news endpoint only covers symbols it also has quotes for,
    # which doesn't include e.g. "BTC/USDT".
    if asset_class == "crypto":
        return []
    return YFinanceProvider().get_news(symbol)


def _load_news_with_sentiment(symbol: str, asset_class: str) -> tuple[list[dict], dict]:
    """Fetches this symbol's news and tags each headline bullish/bearish/
    neutral via the keyword heuristic in news_scoring -- feeds the "📰 新聞
    熱門股" page's per-symbol news score. Deliberately NOT wired into
    decision_engine/DecisionEngine: this is a separate, exploratory signal
    the user asked to see displayed with its supporting article links, not a
    change to how BUY/SELL/auto-trade decisions are made."""
    news = _load_news(symbol, asset_class)
    sentiment = score_news_batch(news)
    return news, sentiment


# Regenerating forward-looking picks needs an actual LLM call (Gemini's free
# tier), unlike the free/instant keyword tagging above -- gated to at most
# once per hour (rather than every ~5-minute pipeline tick) to stay
# comfortably inside free-tier rate limits and avoid unnecessary latency/
# cost. Cross-symbol "might benefit later" reasoning also doesn't need to
# be any fresher than that -- it's about emerging trends, not live prices.
FORWARD_LOOKING_PICKS_TTL_SECONDS = 3600


def _get_forward_looking_picks(results: list[dict], previous_payload: dict) -> dict:
    """Per user request: "不要按照現在新聞的趨勢走...根據你收集到的資訊去做判斷"
    -- reason across the whole watchlist's collected news to flag symbols
    that might benefit later from trends showing up in OTHER symbols' news,
    even before their own news catches up. See llm_provider.py for why this
    needs actual language understanding rather than the keyword tagging in
    news_scoring.py, and for the fail-safe-empty behavior on any error."""
    previous = previous_payload.get("forward_looking_picks") or {}
    previous_generated_at = previous.get("generated_at")
    if previous_generated_at:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous_generated_at)).total_seconds()
            if age < FORWARD_LOOKING_PICKS_TTL_SECONDS:
                return previous
        except (TypeError, ValueError):
            pass  # unparseable timestamp from an older schema -- just regenerate

    provider = GeminiProvider()
    # Non-secret diagnostic only (true/false, never the key itself) -- lets
    # the dashboard/README troubleshooting distinguish "no key configured"
    # from "key configured but Gemini found nothing confident this cycle",
    # which otherwise look identical from the outside (both show 0 picks).
    key_configured = bool(provider.api_key)
    try:
        news_by_symbol = {r["symbol"]: r.get("news", []) for r in results}
        valid_symbols = set(news_by_symbol.keys())
        outcome = provider.predict_future_beneficiaries(news_by_symbol, valid_symbols)
    except Exception as exc:
        logger.warning("Forward-looking picks generation failed, keeping previous result: %s", exc)
        return previous
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "picks": outcome["picks"],
        "key_configured": key_configured,
        "status": outcome["status"],
        "detail": outcome["detail"],  # already sanitized in llm_provider.py -- safe to persist publicly
    }


TAIEX_SYMBOL = "^TWII"  # Yahoo Finance ticker for the Taiwan Weighted Index (加權股價指數)


def _fetch_taiex_snapshot(previous_taiex: dict | None) -> dict | None:
    """A single overall "is the whole Taiwan market up or down today"
    figure -- distinct from any individual stock pick, this is the
    broad-market context users look for first (per user request: "大盤
    總共" = the benchmark index as a whole). Mirrors the same carry-forward-
    when-closed and prev-close-based change_pct logic every individual
    symbol already uses, just for the index itself rather than a strategy
    signal -- no regime/strategy/decision-engine analysis needed here."""
    market_open = is_market_open("taiwan")
    if not market_open and previous_taiex:
        return {**previous_taiex, "market_open": False}
    try:
        df = _load_ohlcv(TAIEX_SYMBOL, "taiwan")
        if df.empty or pd.isna(df["close"].iloc[-1]):
            return previous_taiex
        prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 and not pd.isna(df["close"].iloc[-2]) else None
        price = float(df["close"].iloc[-1])
        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else None
        change_pts = round(price - prev_close, 2) if prev_close else None
        return {
            "symbol": TAIEX_SYMBOL, "price": price, "change_pct": change_pct, "change_pts": change_pts,
            "as_of": str(df.index[-1]), "market_open": market_open,
        }
    except Exception as exc:
        logger.warning("Failed fetching TAIEX snapshot: %s", exc)
        return previous_taiex


def _json_safe(obj):
    """Recursively replaces NaN/Infinity floats with None so json.dump produces
    strictly valid JSON. Python's json module writes bare `NaN` / `Infinity`
    tokens by default, which round-trip fine in Python but are rejected by
    every browser's JSON.parse (per RFC 8259) -- a single NaN anywhere in the
    payload silently breaks the whole dashboard fetch with no error visible
    on the Python side that produced it.
    """
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _extract_indicators(features: pd.DataFrame) -> dict:
    """Pulls a small, human-readable subset of the 300+ engineered features
    (RSI/MACD/moving averages/volume/ATR) for display on the dashboard's
    "詳細" card view -- the full feature matrix stays internal to the
    strategy/backtest layer.
    """
    last = features.iloc[-1]

    def g(col: str, digits: int = 2):
        val = last[col] if col in features.columns else float("nan")
        return round(float(val), digits)

    return {
        "rsi_14": g("rsi_14", 1),
        "macd_hist": g("macd_hist", 4),
        "sma_20": g("sma_20", 4),
        "sma_50": g("sma_50", 4),
        "volume_ratio": g("volume_ratio", 2),
        "atr_pct": round(g("atr_pct", 6) * 100, 2),
    }


def _analyze_symbol(symbol: str, asset_class: str, df: pd.DataFrame, macro_snapshot: dict,
                     sentiment_snapshot: dict, portfolio_equity_curve: pd.Series | None = None,
                     portfolio_risk_status: dict | None = None,
                     drawdown_breaker: DrawdownCircuitBreaker | None = None,
                     loss_limit_monitor: LossLimitMonitor | None = None,
                     returns_by_symbol: dict[str, pd.Series] | None = None,
                     asset_class_of: dict[str, str] | None = None) -> dict | None:
    if df.empty or len(df) < 80:
        logger.warning("Skipping %s: insufficient data (%d rows)", symbol, len(df))
        return None
    if pd.isna(df["close"].iloc[-1]):
        logger.warning("Skipping %s: latest close price is NaN (bad data from provider)", symbol)
        return None

    features = FeaturePipeline().build(df)
    regime_state = RegimeDetector().detect(df)

    strategies = [TrendFollowingStrategy(), MeanReversionStrategy(), BreakoutStrategy(), MomentumStrategy()]
    combiner = StrategyCombiner(strategies)
    combined = combiner.combine(symbol, features, regime_state)

    engine = BacktestEngine(commission_bps=settings.default_commission_bps, slippage_bps=settings.default_slippage_bps,
                             risk_free_rate=settings.risk_free_rate)
    backtest_results = {strat.name: engine.run(symbol, strat, features) for strat in strategies}
    backtest_snapshot = {name: result.metrics for name, result in backtest_results.items()}

    # backtest_snapshot above already uses each strategy's own full-history
    # equity curve, which is exactly right for "how has this strategy
    # performed historically." The risk *veto*, below, deliberately does NOT
    # reuse that curve -- gating trade entries on a single stock's own
    # historical backtest conflates "this individual name had a rough patch
    # sometime in the last ~90 days" (routine for any single equity) with
    # "our actual trading capital is currently bleeding" (what a circuit
    # breaker is supposed to catch). That mismatch made the drawdown breaker
    # -- once its hysteresis persistence actually worked -- get permanently
    # stuck tripped for the large majority of the watchlist, since ordinary
    # single-name volatility routinely exceeds a 20% max-drawdown bar. The
    # veto is checked against the real, shared 24-hour auto-trader account's
    # own equity curve instead (computed once in run_daily_pipeline and
    # passed in here), which is what "the portfolio is bleeding" should
    # actually mean, and is identical for every symbol in a given run.
    risk_status = portfolio_risk_status or {
        "current_drawdown_pct": 0.0, "drawdown_circuit_breaker_tripped": False,
        "halted": False, "breached": [], "daily_pnl_pct": 0.0, "weekly_pnl_pct": 0.0, "monthly_pnl_pct": 0.0,
    }

    decision_engine = DecisionEngine([TechnicalAgent(combiner, RegimeDetector()), MacroAgent(),
                                       RiskAgent(drawdown_breaker=drawdown_breaker or DrawdownCircuitBreaker(),
                                                 loss_limit_monitor=loss_limit_monitor or LossLimitMonitor())])
    context = AgentContext(symbol=symbol, features=features, macro_snapshot=macro_snapshot,
                            sentiment_snapshot=sentiment_snapshot, equity_curve=portfolio_equity_curve,
                            returns_by_symbol=returns_by_symbol, asset_class_of=asset_class_of)
    decision = decision_engine.decide(context)

    # "漲跌幅" convention used by every stock ticker/app: today's price vs.
    # the previous trading day's close, not vs. whatever price the last
    # poll happened to see a few minutes ago. The frontend used to diff
    # consecutive history.json snapshots for this, which -- especially now
    # that free data only actually refreshes every 15-20 minutes (see
    # README) -- mostly compared a price against itself and showed a
    # meaningless "0%" between real updates.
    prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 and not pd.isna(df["close"].iloc[-2]) else None
    change_pct = round((float(df["close"].iloc[-1]) - prev_close) / prev_close * 100, 2) if prev_close else None

    news, news_sentiment = _load_news_with_sentiment(symbol, asset_class)

    return {
        "symbol": symbol,
        "asset_class": asset_class,
        "last_price": float(df["close"].iloc[-1]),
        "change_pct": change_pct,
        "as_of": str(df.index[-1]),
        "regime": {
            "state": regime_state.regime.value,
            "trend_strength_adx": regime_state.trend_strength,
            "volatility_percentile": regime_state.volatility_percentile,
            "direction": regime_state.direction,
        },
        "signal": combined.to_dict(),
        "decision_engine": decision.to_dict(),
        "risk_status": risk_status,
        "backtest": backtest_snapshot,
        "feature_count": FeaturePipeline.feature_count(features),
        "indicators": _extract_indicators(features),
        "news": news,
        "news_sentiment": news_sentiment,
    }


def _load_previous_payload() -> dict:
    path = DOCS_DATA_DIR / "signals_latest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _equity_series_from_history(equity_history: list[dict]) -> pd.Series:
    """Builds a datetime-indexed equity curve from auto_trader's
    equity_history (list of {"time": iso str, "equity": float}), the only
    real, persistent, portfolio-level equity curve this pipeline has access
    to -- used as the shared risk-veto input for every symbol instead of
    each stock's own single-strategy backtest curve."""
    if not equity_history:
        return pd.Series(dtype=float)
    times = pd.to_datetime([e["time"] for e in equity_history])
    values = [e["equity"] for e in equity_history]
    return pd.Series(values, index=times).sort_index()


def _analyze_pairs(price_cache: dict[str, pd.Series], errors: list[dict]) -> list[dict]:
    results = []
    strategy = PairsTradingStrategy()
    for symbol_a, symbol_b, asset_class in PAIR_WATCHLIST:
        pair_label = f"{symbol_a}/{symbol_b}"
        close_a, close_b = price_cache.get(symbol_a), price_cache.get(symbol_b)
        if close_a is None or close_b is None or len(close_a) < 80 or len(close_b) < 80:
            continue
        try:
            signal = strategy.analyze(symbol_a, close_a, symbol_b, close_b)
            results.append({"asset_class": asset_class, **signal.to_dict()})
        except Exception as exc:
            logger.warning("Pairs analysis failed for %s: %s", pair_label, exc)
            errors.append({"symbol": pair_label, "error": str(exc)})
    return results


def run_daily_pipeline() -> dict:
    results = []
    errors = []
    price_cache: dict[str, pd.Series] = {}

    # Carry-forward source for symbols whose market is currently closed --
    # running every 5 minutes around the clock only makes sense if closed
    # markets are skipped rather than uselessly re-analyzed against data
    # that hasn't changed since the last close.
    previous_payload = _load_previous_payload()
    previous_by_symbol = {s["symbol"]: s for s in previous_payload.get("signals", [])}
    previous_pairs_by_key = {(p["symbol_a"], p["symbol_b"]): p for p in previous_payload.get("pairs_signals", [])}
    taiex = _fetch_taiex_snapshot(previous_payload.get("taiex"))

    sentiment = SentimentProvider().get_crypto_fear_greed()
    sentiment_snapshot = {"crypto_fear_greed": sentiment}
    macro_snapshot = MacroProvider().get_dxy_and_yields_snapshot()  # returns all-None values if FRED_API_KEY unset
    asset_class_of = {s: ac for ac, syms in WATCHLIST.items() for s in syms}

    # Portfolio-level risk gating, shared across every symbol: the 24-hour
    # auto-trader's own equity_history is the only real, persistent trading
    # equity curve this pipeline has access to, so it's what the risk veto
    # should reflect ("is our actual capital bleeding"), not each
    # individual stock's own historical backtest (routine single-name
    # volatility routinely exceeds a 20% drawdown bar, which made the risk
    # veto -- once its hysteresis persistence actually worked -- get stuck
    # tripped for most of the watchlist; see auto_trader module docstring).
    auto_state_path = DOCS_DATA_DIR / "auto_trade_state.json"
    auto_state = auto_trader.load_state(auto_state_path)
    portfolio_equity_curve = _equity_series_from_history(auto_state.get("equity_history", []))
    prior_portfolio_tripped = bool(
        (previous_payload.get("portfolio_risk_status") or {}).get("drawdown_circuit_breaker_tripped", False)
    )
    portfolio_breaker = DrawdownCircuitBreaker(initially_tripped=prior_portfolio_tripped)
    portfolio_loss_monitor = LossLimitMonitor()
    if len(portfolio_equity_curve) > 1:
        portfolio_drawdown_breached = portfolio_breaker.update(portfolio_equity_curve)
        portfolio_loss_status = portfolio_loss_monitor.check(portfolio_equity_curve)
        portfolio_risk_status = {
            "current_drawdown_pct": round(max_drawdown(portfolio_equity_curve) * 100, 2),
            "drawdown_circuit_breaker_tripped": portfolio_drawdown_breached,
            **portfolio_loss_status.to_dict(),
        }
    else:
        portfolio_risk_status = {
            "current_drawdown_pct": 0.0, "drawdown_circuit_breaker_tripped": False,
            "halted": False, "breached": [], "daily_pnl_pct": 0.0, "weekly_pnl_pct": 0.0, "monthly_pnl_pct": 0.0,
        }

    for asset_class, symbols in WATCHLIST.items():
        for symbol in symbols:
            market_open = is_market_open(asset_class)
            if not market_open:
                carried = previous_by_symbol.get(symbol)
                if carried:
                    # Price/technicals are correctly frozen while this
                    # symbol's market is closed (no new candle to analyze),
                    # but news keeps getting published around the clock --
                    # freezing news_sentiment along with the price meant
                    # Taiwan stocks (market open only ~4.5h/weekday) almost
                    # never refreshed their news score, making them nearly
                    # invisible on the "📰 新聞熱門股" page despite being
                    # this project's primary focus. Refresh news/sentiment
                    # on every tick regardless of market hours; everything
                    # else about the carried entry stays untouched.
                    news, news_sentiment = _load_news_with_sentiment(symbol, asset_class)
                    results.append({**carried, "market_open": False, "news": news, "news_sentiment": news_sentiment})
                    continue
                # No prior data yet (e.g. a symbol just added to the
                # watchlist) -- fall through and analyze once anyway so the
                # dashboard isn't empty for it, but market_open below still
                # honestly reflects that the market is actually closed right
                # now; being freshly analyzed doesn't make it "open".
            try:
                df = _load_ohlcv(symbol, asset_class)
                if not df.empty:
                    price_cache[symbol] = df["close"]
                # Correlation check needs every other symbol's returns too, but
                # this pipeline analyzes one symbol at a time -- use whatever's
                # accumulated in price_cache so far this run (every symbol
                # already processed, plus this one) as a practical stand-in for
                # "the rest of the portfolio" rather than requiring a full
                # second pass over the watchlist just for this.
                returns_by_symbol = {s: c.pct_change().dropna() for s, c in price_cache.items()}
                res = _analyze_symbol(symbol, asset_class, df, macro_snapshot, sentiment_snapshot,
                                       portfolio_equity_curve=portfolio_equity_curve,
                                       portfolio_risk_status=portfolio_risk_status,
                                       drawdown_breaker=portfolio_breaker,
                                       loss_limit_monitor=portfolio_loss_monitor,
                                       returns_by_symbol=returns_by_symbol, asset_class_of=asset_class_of)
                if res:
                    res["market_open"] = market_open
                    results.append(res)
                else:
                    # _analyze_symbol returns None (rather than raising) for
                    # empty/too-short/NaN data -- e.g. every configured data
                    # provider being unreachable for this symbol. That used
                    # to vanish the symbol from the payload with no trace
                    # anywhere, which let a persistent provider outage (see
                    # CCXTProvider's exchange fallback) go unnoticed for
                    # days. Surface it in errors like any other failure.
                    errors.append({"symbol": symbol, "error": f"no usable OHLCV data ({len(df)} rows)"})
            except Exception as exc:
                logger.error("Failed analyzing %s: %s", symbol, exc)
                errors.append({"symbol": symbol, "error": str(exc), "trace": traceback.format_exc(limit=3)})

    fresh_pairs = _analyze_pairs(price_cache, errors)
    fresh_pairs_keys = {(p["symbol_a"], p["symbol_b"]) for p in fresh_pairs}
    pairs_signals = fresh_pairs + [
        p for key, p in previous_pairs_by_key.items() if key not in fresh_pairs_keys
    ]

    forward_looking_picks = _get_forward_looking_picks(results, previous_payload)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "watchlist_size": sum(len(v) for v in WATCHLIST.values()),
        "successful": len(results),
        "errors": errors,
        "market_sentiment": sentiment_snapshot,
        "macro_snapshot": macro_snapshot,
        "portfolio_risk_status": portfolio_risk_status,
        "taiex": taiex,
        "signals": results,
        "pairs_signals": pairs_signals,
        "forward_looking_picks": forward_looking_picks,
    }

    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DATA_DIR / "signals_latest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(payload), f, indent=2, default=str, allow_nan=False)
    logger.info("Wrote %d signals to %s", len(results), out_path)

    # Always-on paper-trading auto-follower: advances its own persistent
    # virtual portfolio by one tick every pipeline run (this function already
    # runs ~24/7 via the self-chaining GitHub Actions workflow), so auto-follow
    # keeps trading even when nobody has the dashboard open -- unlike the
    # original browser-only auto-trade toggle in docs/assets/paper.js, which
    # only ever evaluates while that page is sitting open in a tab.
    try:
        auto_state = auto_trader.run_tick(results, auto_state)
        auto_trader.save_state(auto_state_path, auto_state)
    except Exception as exc:
        logger.error("Auto-trader tick failed (signals output above is unaffected): %s", exc)

    history_path = DOCS_DATA_DIR / "history.json"
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text())
        except Exception:
            history = []
    history.append({
        "generated_at": payload["generated_at"],
        "signals": [{"symbol": r["symbol"], "action": r["signal"]["final_action"],
                     "confidence": r["signal"]["confidence"], "price": r["last_price"]} for r in results],
    })
    history_path.write_text(json.dumps(_json_safe(history[-90:]), indent=2, default=str, allow_nan=False))  # keep last 90 runs

    return payload


if __name__ == "__main__":
    run_daily_pipeline()
