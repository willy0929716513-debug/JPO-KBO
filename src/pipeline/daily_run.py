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
from src.data.providers.ccxt_provider import CCXTProvider
from src.data.providers.macro_provider import MacroProvider
from src.data.providers.sentiment_provider import SentimentProvider
from src.data.providers.yfinance_provider import YFinanceProvider
from src.features.feature_pipeline import FeaturePipeline
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
                     sentiment_snapshot: dict) -> dict | None:
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

    # Risk status is checked against this symbol's own trend-following equity
    # curve as a stand-in for a live portfolio equity curve (which doesn't
    # exist yet -- no persistent broker state), so it reflects "would this
    # strategy on this symbol currently be within its risk limits." Only the
    # most recent window is used for that check -- the backtest spans years,
    # and a >20% drawdown *somewhere* over that long a history is normal, not
    # a sign of a live risk problem *today*. Using the full history here made
    # the risk veto trip on almost every symbol, which is a real bug, not a
    # genuinely risk-averse call. The full-history curve is still used for
    # backtest_snapshot below, where "how has this strategy performed
    # historically" is exactly what should be shown.
    trend_equity_full = backtest_results["trend_following"].equity_curve
    recent_window = min(90, len(trend_equity_full))
    trend_equity_recent = trend_equity_full.tail(recent_window)

    loss_status = LossLimitMonitor().check(trend_equity_recent)
    drawdown_breached = DrawdownCircuitBreaker().update(trend_equity_recent)
    risk_status = {
        "current_drawdown_pct": round(max_drawdown(trend_equity_recent) * 100, 2),
        "drawdown_circuit_breaker_tripped": drawdown_breached,
        **loss_status.to_dict(),
    }

    decision_engine = DecisionEngine([TechnicalAgent(combiner, RegimeDetector()), MacroAgent(),
                                       RiskAgent(loss_limit_monitor=LossLimitMonitor())])
    context = AgentContext(symbol=symbol, features=features, macro_snapshot=macro_snapshot,
                            sentiment_snapshot=sentiment_snapshot, equity_curve=trend_equity_recent)
    decision = decision_engine.decide(context)

    return {
        "symbol": symbol,
        "asset_class": asset_class,
        "last_price": float(df["close"].iloc[-1]),
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
    }


def _load_previous_payload() -> dict:
    path = DOCS_DATA_DIR / "signals_latest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _analyze_pairs(price_cache: dict[str, pd.Series]) -> list[dict]:
    results = []
    strategy = PairsTradingStrategy()
    for symbol_a, symbol_b, asset_class in PAIR_WATCHLIST:
        close_a, close_b = price_cache.get(symbol_a), price_cache.get(symbol_b)
        if close_a is None or close_b is None or len(close_a) < 80 or len(close_b) < 80:
            continue
        try:
            signal = strategy.analyze(symbol_a, close_a, symbol_b, close_b)
            results.append({"asset_class": asset_class, **signal.to_dict()})
        except Exception as exc:
            logger.warning("Pairs analysis failed for %s/%s: %s", symbol_a, symbol_b, exc)
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

    sentiment = SentimentProvider().get_crypto_fear_greed()
    sentiment_snapshot = {"crypto_fear_greed": sentiment}
    macro_snapshot = MacroProvider().get_dxy_and_yields_snapshot()  # returns all-None values if FRED_API_KEY unset

    for asset_class, symbols in WATCHLIST.items():
        for symbol in symbols:
            market_open = is_market_open(asset_class)
            if not market_open:
                carried = previous_by_symbol.get(symbol)
                if carried:
                    results.append({**carried, "market_open": False})
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
                res = _analyze_symbol(symbol, asset_class, df, macro_snapshot, sentiment_snapshot)
                if res:
                    res["market_open"] = market_open
                    results.append(res)
            except Exception as exc:
                logger.error("Failed analyzing %s: %s", symbol, exc)
                errors.append({"symbol": symbol, "error": str(exc), "trace": traceback.format_exc(limit=3)})

    fresh_pairs = _analyze_pairs(price_cache)
    fresh_pairs_keys = {(p["symbol_a"], p["symbol_b"]) for p in fresh_pairs}
    pairs_signals = fresh_pairs + [
        p for key, p in previous_pairs_by_key.items() if key not in fresh_pairs_keys
    ]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "watchlist_size": sum(len(v) for v in WATCHLIST.values()),
        "successful": len(results),
        "errors": errors,
        "market_sentiment": sentiment_snapshot,
        "macro_snapshot": macro_snapshot,
        "signals": results,
        "pairs_signals": pairs_signals,
    }

    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DATA_DIR / "signals_latest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(payload), f, indent=2, default=str, allow_nan=False)
    logger.info("Wrote %d signals to %s", len(results), out_path)

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
