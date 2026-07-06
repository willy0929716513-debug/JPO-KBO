"""Regression tests for a bug found during a full-system audit: a fresh
DrawdownCircuitBreaker() was instantiated on every single pipeline run
(every ~5 minutes), so its "stays halted until equity recovers past
reset_drawdown_pct" hysteresis never actually applied -- it silently
degraded into a stateless instantaneous threshold check. Fixed by
persisting the prior tripped state (read back from last run's own output
payload) and seeding a fresh breaker with it via `initially_tripped`.
"""
import numpy as np
import pandas as pd
import pytest

import src.pipeline.daily_run as daily_run
from src.risk.portfolio_risk import DrawdownCircuitBreaker


def test_initially_tripped_preserves_hysteresis_between_reset_and_max():
    """dd sitting between reset_drawdown_pct (10%) and max_drawdown_pct (20%)
    should stay tripped if it already was, and stay untripped if it wasn't --
    this is exactly the state a fresh, un-seeded instance could never represent."""
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    # ~15% drawdown from peak: between the 10% reset and 20% max thresholds.
    equity = pd.Series([100_000] * 3 + [85_000] * 7, index=dates)

    already_tripped = DrawdownCircuitBreaker(max_drawdown_pct=0.20, reset_drawdown_pct=0.10, initially_tripped=True)
    assert already_tripped.update(equity) is True  # stays halted -- hasn't recovered past reset yet

    fresh = DrawdownCircuitBreaker(max_drawdown_pct=0.20, reset_drawdown_pct=0.10, initially_tripped=False)
    assert fresh.update(equity) is False  # never breached 20% itself, so a fresh one correctly stays untripped


def _synthetic_df(seed: int, n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    high, low = close * 1.005, close * 0.995
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume}, index=dates)


@pytest.fixture(autouse=True)
def _stub_external_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_run, "DOCS_DATA_DIR", tmp_path)
    monkeypatch.setattr(daily_run, "WATCHLIST", {"equity": ["SYM"]})
    monkeypatch.setattr(daily_run, "PAIR_WATCHLIST", [])
    monkeypatch.setattr(daily_run, "_load_ohlcv", lambda symbol, asset_class, interval="1d": _synthetic_df(42))

    class _StubSentiment:
        def get_crypto_fear_greed(self):
            return {"value": 50, "classification": "Neutral"}

    class _StubMacro:
        def get_dxy_and_yields_snapshot(self):
            return {}

    monkeypatch.setattr(daily_run, "SentimentProvider", _StubSentiment)
    monkeypatch.setattr(daily_run, "MacroProvider", _StubMacro)
    monkeypatch.setattr(daily_run, "is_market_open", lambda asset_class: True)
    return tmp_path


def test_pipeline_seeds_breaker_from_previous_run_tripped_state(monkeypatch):
    """run_daily_pipeline should read last run's own `risk_status.
    drawdown_circuit_breaker_tripped` for a symbol and pass it through as
    this run's `prior_drawdown_tripped`, rather than always starting fresh."""
    captured_initially_tripped = []
    real_breaker = daily_run.DrawdownCircuitBreaker

    def _spy_breaker(*args, **kwargs):
        captured_initially_tripped.append(kwargs.get("initially_tripped", False))
        return real_breaker(*args, **kwargs)

    monkeypatch.setattr(daily_run, "DrawdownCircuitBreaker", _spy_breaker)

    # First run: no prior payload yet, so it must seed with False (the safe default).
    daily_run.run_daily_pipeline()
    assert captured_initially_tripped[0] is False

    # Simulate the previous run having ended with this symbol's breaker tripped.
    payload_path = daily_run.DOCS_DATA_DIR / "signals_latest.json"
    import json
    payload = json.loads(payload_path.read_text())
    payload["signals"][0]["risk_status"]["drawdown_circuit_breaker_tripped"] = True
    payload_path.write_text(json.dumps(payload))

    captured_initially_tripped.clear()
    daily_run.run_daily_pipeline()
    assert captured_initially_tripped[0] is True  # carried the prior tripped state forward


def test_pipeline_populates_returns_by_symbol_and_asset_class_of(monkeypatch):
    """The correlation-limit check inside RiskAgent was dead code in
    production because AgentContext.returns_by_symbol/asset_class_of were
    never populated by the pipeline. Confirms run_daily_pipeline now passes
    real, non-empty data through to _analyze_symbol."""
    captured = {}
    real_analyze = daily_run._analyze_symbol

    def _spy_analyze(symbol, asset_class, df, macro_snapshot, sentiment_snapshot, **kwargs):
        captured["returns_by_symbol"] = kwargs.get("returns_by_symbol")
        captured["asset_class_of"] = kwargs.get("asset_class_of")
        return real_analyze(symbol, asset_class, df, macro_snapshot, sentiment_snapshot, **kwargs)

    monkeypatch.setattr(daily_run, "_analyze_symbol", _spy_analyze)
    daily_run.run_daily_pipeline()

    assert captured["returns_by_symbol"] is not None
    assert "SYM" in captured["returns_by_symbol"]
    assert captured["asset_class_of"] == {"SYM": "equity"}
