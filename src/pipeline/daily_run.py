"""The single orchestration entry point that ties every module together:

  fetch data -> build features -> detect regime -> run strategies ->
  combine into a final signal -> run a quick backtest snapshot ->
  export everything as JSON for the GitHub Pages dashboard.

Run it with `python scripts/run_pipeline.py`. It's also what the daily
GitHub Actions workflow calls. Every network call is wrapped so a single
symbol failing (e.g. Yahoo Finance hiccup) never aborts the whole run.
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone

import pandas as pd

from src.backtest.engine import BacktestEngine
from src.config import DOCS_DATA_DIR, settings
from src.data.providers.ccxt_provider import CCXTProvider
from src.data.providers.sentiment_provider import SentimentProvider
from src.data.providers.yfinance_provider import YFinanceProvider
from src.features.feature_pipeline import FeaturePipeline
from src.regime.detector import RegimeDetector
from src.strategies import (
    BreakoutStrategy, MeanReversionStrategy, MomentumStrategy,
    StrategyCombiner, TrendFollowingStrategy,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Curated default watchlist across every asset class the prompt asked for.
# Kept small enough to run comfortably inside a GitHub Actions job.
WATCHLIST = {
    "equity": ["AAPL", "MSFT", "NVDA", "TSLA"],
    "etf": ["SPY", "QQQ"],
    "taiwan": ["2330.TW"],
    "metal": ["GC=F", "SI=F"],
    "energy": ["CL=F"],
    "forex": ["EURUSD=X"],
    "crypto": ["BTC/USDT", "ETH/USDT"],
}


def _asset_class_of(symbol: str) -> str:
    for cls, syms in WATCHLIST.items():
        if symbol in syms:
            return cls
    return "other"


def _load_ohlcv(symbol: str, asset_class: str, interval: str = "1d") -> pd.DataFrame:
    if asset_class == "crypto":
        return CCXTProvider().get_ohlcv(symbol, interval)
    return YFinanceProvider().get_ohlcv(symbol, interval)


def _analyze_symbol(symbol: str, asset_class: str) -> dict | None:
    df = _load_ohlcv(symbol, asset_class)
    if df.empty or len(df) < 80:
        logger.warning("Skipping %s: insufficient data (%d rows)", symbol, len(df))
        return None

    features = FeaturePipeline().build(df)
    regime_state = RegimeDetector().detect(df)

    strategies = [TrendFollowingStrategy(), MeanReversionStrategy(), BreakoutStrategy(), MomentumStrategy()]
    combiner = StrategyCombiner(strategies)
    combined = combiner.combine(symbol, features, regime_state)

    engine = BacktestEngine(commission_bps=settings.default_commission_bps, slippage_bps=settings.default_slippage_bps,
                             risk_free_rate=settings.risk_free_rate)
    backtest_snapshot = {
        strat.name: engine.run(symbol, strat, features).metrics for strat in strategies
    }

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
        "backtest": backtest_snapshot,
        "feature_count": FeaturePipeline.feature_count(features),
    }


def run_daily_pipeline() -> dict:
    results = []
    errors = []
    for asset_class, symbols in WATCHLIST.items():
        for symbol in symbols:
            try:
                res = _analyze_symbol(symbol, asset_class)
                if res:
                    results.append(res)
            except Exception as exc:
                logger.error("Failed analyzing %s: %s", symbol, exc)
                errors.append({"symbol": symbol, "error": str(exc), "trace": traceback.format_exc(limit=3)})

    sentiment = SentimentProvider().get_crypto_fear_greed()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "watchlist_size": sum(len(v) for v in WATCHLIST.values()),
        "successful": len(results),
        "errors": errors,
        "market_sentiment": {"crypto_fear_greed": sentiment},
        "signals": results,
    }

    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DATA_DIR / "signals_latest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
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
    history_path.write_text(json.dumps(history[-90:], indent=2, default=str))  # keep last 90 runs

    return payload


if __name__ == "__main__":
    run_daily_pipeline()
