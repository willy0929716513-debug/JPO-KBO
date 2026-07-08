"""Tests for the server-side 24/7 paper-trading auto-follower
(src/pipeline/auto_trader.py) -- runs inside the pipeline itself (already
executing ~24/7 via the self-chaining GitHub Actions workflow) instead of
requiring a browser tab to stay open, unlike the original client-side
auto-trade toggle in docs/assets/paper.js.
"""
import json

import numpy as np
import pandas as pd
import pytest

import src.pipeline.daily_run as daily_run
from src.pipeline import auto_trader


def _signal(symbol, action, price, stop_loss=None, take_profit=None, vetoed=False, de_action=None,
            confidence=0.5, votes=None, backtest=None, asset_class="taiwan"):
    return {
        "symbol": symbol, "last_price": price, "asset_class": asset_class,
        "signal": {"final_action": action, "confidence": confidence, "stop_loss": stop_loss,
                   "take_profit": take_profit, "votes": votes or []},
        "decision_engine": {"action": de_action or action, "confidence": confidence, "vetoed": vetoed},
        "backtest": backtest or {},
    }


def test_opens_position_for_every_recommendation():
    state = auto_trader._empty_state()
    signals = [_signal("A", "BUY", 100.0), _signal("B", "SELL", 50.0), _signal("C", "HOLD", 10.0)]
    state = auto_trader.run_tick(signals, state)

    assert set(state["positions"].keys()) == {"A", "B"}
    assert state["positions"]["A"]["side"] == "long"
    assert state["positions"]["B"]["side"] == "short"


def test_position_and_history_record_asset_class_for_unit_labeling():
    """qty is a share count, not a board-lot (張) count -- the frontend needs
    asset_class on positions/history to label it correctly (股 vs 單位)."""
    state = auto_trader._empty_state()
    state = auto_trader.run_tick([_signal("A", "BUY", 100.0, asset_class="taiwan")], state)
    assert state["positions"]["A"]["asset_class"] == "taiwan"
    assert state["history"][0]["asset_class"] == "taiwan"

    state = auto_trader.run_tick([_signal("A", "HOLD", 100.0, asset_class="taiwan")], state)
    close_entries = [h for h in state["history"] if h["action"] == "close"]
    assert close_entries[0]["asset_class"] == "taiwan"


def test_skips_recommendation_below_min_confidence():
    """Per user request ("不要盲目下單，要經過分析考慮"): a weak signal that
    barely crosses the BUY/SELL threshold shouldn't be acted on."""
    state = auto_trader._empty_state()
    weak = _signal("WEAK", "BUY", 100.0, confidence=0.05)
    strong = _signal("STRONG", "BUY", 100.0, confidence=0.5)
    assert weak["decision_engine"]["confidence"] < auto_trader.AUTO_TRADE_MIN_CONFIDENCE
    state = auto_trader.run_tick([weak, strong], state)

    assert "WEAK" not in state["positions"]
    assert "STRONG" in state["positions"]


def test_skips_recommendation_from_a_historically_losing_strategy():
    """If the vote actually driving the recommendation has a historically
    losing (profit_factor < 1.0) track record for this exact symbol, skip
    it even though the combined signal still says BUY -- avoids blindly
    acting on e.g. a mean-reversion vote known to be a bad fit here."""
    state = auto_trader._empty_state()
    bad_track_record = _signal(
        "BADFIT", "BUY", 100.0, confidence=0.5,
        votes=[{"strategy": "mean_reversion", "action": "BUY", "confidence": 0.6, "weight": 1.5}],
        backtest={"mean_reversion": {"profit_factor": 0.3}},
    )
    good_track_record = _signal(
        "GOODFIT", "BUY", 100.0, confidence=0.5,
        votes=[{"strategy": "trend_following", "action": "BUY", "confidence": 0.6, "weight": 1.5}],
        backtest={"trend_following": {"profit_factor": 2.1}},
    )
    state = auto_trader.run_tick([bad_track_record, good_track_record], state)

    assert "BADFIT" not in state["positions"]
    assert "GOODFIT" in state["positions"]


def test_high_price_asset_still_buys_one_unit_instead_of_being_silently_skipped():
    """Regression test for a real production bug: gold/oil/crypto are priced
    in USD terms while this account's cash is one flat notional pool with
    no currency conversion, so a qualifying candidate's confidence-weighted
    slice of AUTO_TRADE_NOTIONAL ($1,000 under the $10,000 account) can be
    smaller than a single unit's price (e.g. gold at ~$4,113/oz) -- qty
    would round down to 0 and silently exclude that symbol from ever
    trading, no matter how strong its signal. Confirmed via real production
    data (GC=F, confidence 0.232, profit_factor 1.167 -- passed every
    filter but qty computed to 0)."""
    state = auto_trader._empty_state()
    expensive = _signal("GC=F", "SELL", 4113.10, confidence=0.232,
                         backtest={"trend_following": {"profit_factor": 1.167}},
                         votes=[{"strategy": "trend_following", "action": "SELL", "confidence": 0.665, "weight": 1.5}])
    state = auto_trader.run_tick([expensive], state)

    assert "GC=F" in state["positions"]
    assert state["positions"]["GC=F"]["qty"] == 1


def test_position_size_scales_with_confidence():
    """A higher-confidence candidate should get a proportionally larger
    allocation than a lower-confidence one, not an identical flat split.
    Uses enough filler candidates that neither WEAK nor STRONG's computed
    share hits the per-symbol AUTO_TRADE_NOTIONAL cap -- otherwise both
    would just get clamped to the same ceiling and the scaling wouldn't be
    visible in the resulting position size."""
    state = auto_trader._empty_state()
    filler = [_signal(f"FILLER{i}", "BUY", 100.0, confidence=0.5) for i in range(20)]
    # Both above AUTO_TRADE_MIN_CONFIDENCE (0.20) so the confidence-threshold
    # filter doesn't remove either one -- only the sizing should differ.
    weak = _signal("WEAK", "BUY", 100.0, confidence=0.25)
    strong = _signal("STRONG", "BUY", 100.0, confidence=0.9)
    state = auto_trader.run_tick(filler + [weak, strong], state)

    weak_notional = state["positions"]["WEAK"]["qty"] * state["positions"]["WEAK"]["avg_price"]
    strong_notional = state["positions"]["STRONG"]["qty"] * state["positions"]["STRONG"]["avg_price"]
    assert strong_notional < auto_trader.AUTO_TRADE_NOTIONAL  # sanity: didn't just hit the cap
    assert strong_notional > weak_notional


def test_respects_true_multi_agent_decision_not_raw_technical_signal():
    """A vetoed symbol must never open a position, even though the raw
    technical signal says BUY/SELL -- mirrors effectiveAction() in
    docs/assets/common.js exactly."""
    state = auto_trader._empty_state()
    signals = [_signal("VETOED", "SELL", 100.0, vetoed=True)]
    state = auto_trader.run_tick(signals, state)
    assert state["positions"] == {}


def test_stop_loss_force_closes_open_position():
    state = auto_trader._empty_state()
    state["positions"]["A"] = {"side": "long", "qty": 10, "avg_price": 100.0, "opened_at": "t", "stop_loss": 90.0, "take_profit": None}
    signals = [_signal("A", "HOLD", 85.0)]  # price fell through the stop
    state = auto_trader.run_tick(signals, state)

    assert "A" not in state["positions"]
    assert state["history"][0]["close_reason"] == "stop_loss"
    assert state["history"][0]["price"] == 90.0  # exited at the stop, not the live price
    assert state["realized_pnl"] < 0


def test_take_profit_force_closes_open_position():
    state = auto_trader._empty_state()
    state["positions"]["A"] = {"side": "short", "qty": 10, "avg_price": 100.0, "opened_at": "t", "stop_loss": None, "take_profit": 80.0}
    signals = [_signal("A", "HOLD", 75.0)]  # price fell through the short's take-profit
    state = auto_trader.run_tick(signals, state)

    assert "A" not in state["positions"]
    assert state["history"][0]["close_reason"] == "take_profit"
    assert state["history"][0]["price"] == 80.0
    assert state["realized_pnl"] > 0


def test_closes_position_when_signal_flips_away():
    """When the signal flips to the opposite side, the old position is
    closed and (since that side is still actively recommended) a new
    position in the new direction opens immediately in the same tick --
    rather than sitting flat for one extra cycle."""
    state = auto_trader._empty_state()
    state["positions"]["A"] = {"side": "long", "qty": 10, "avg_price": 100.0, "opened_at": "t", "stop_loss": None, "take_profit": None}
    signals = [_signal("A", "SELL", 105.0)]
    state = auto_trader.run_tick(signals, state)

    assert state["positions"]["A"]["side"] == "short"
    close_entries = [h for h in state["history"] if h["action"] == "close"]
    assert len(close_entries) == 1
    assert close_entries[0]["close_reason"] is None
    assert close_entries[0]["side"] == "long"


def test_budget_splits_across_many_simultaneous_candidates():
    """A batch of simultaneous recommendations larger than the fixed lot size
    would allow should still all get opened -- same fix as the client-side
    round-robin/budget-split logic."""
    state = auto_trader._empty_state()
    signals = [_signal(f"SYM{i}", "BUY", 100.0) for i in range(30)]
    state = auto_trader.run_tick(signals, state)
    assert len(state["positions"]) == 30


def test_state_round_trips_through_json(tmp_path):
    state = auto_trader._empty_state()
    signals = [_signal("A", "BUY", 100.0, stop_loss=90.0, take_profit=120.0)]
    state = auto_trader.run_tick(signals, state)

    path = tmp_path / "auto_trade_state.json"
    auto_trader.save_state(path, state)
    reloaded = auto_trader.load_state(path)

    assert reloaded["positions"]["A"]["avg_price"] == 100.0
    assert reloaded["cash"] == state["cash"]


def test_load_state_falls_back_to_empty_on_missing_or_corrupt_file(tmp_path):
    missing = auto_trader.load_state(tmp_path / "nonexistent.json")
    assert missing["cash"] == auto_trader.AUTO_TRADER_STARTING_CASH

    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text("{not valid json")
    corrupt = auto_trader.load_state(corrupt_path)
    assert corrupt["cash"] == auto_trader.AUTO_TRADER_STARTING_CASH


def test_load_state_self_heals_when_persisted_capital_is_stale(tmp_path):
    """A file written under a since-changed AUTO_TRADER_STARTING_CASH (e.g.
    the 10,000,000 -> 10,000 capital split) must not just keep resuming
    forever -- load_state() should re-seed it fresh so the very next pipeline
    tick self-heals without a manual data commit racing the pipeline's own
    writes to the same file."""
    path = tmp_path / "auto_trade_state.json"
    stale_state = auto_trader._empty_state()
    stale_state["starting_cash"] = 10_000_000.0
    stale_state["cash"] = 7_000_000.0
    stale_state["positions"]["A"] = {"side": "long", "qty": 1000, "avg_price": 100.0, "opened_at": "t"}
    auto_trader.save_state(path, stale_state)

    reloaded = auto_trader.load_state(path)
    assert reloaded["starting_cash"] == auto_trader.AUTO_TRADER_STARTING_CASH
    assert reloaded["cash"] == auto_trader.AUTO_TRADER_STARTING_CASH
    assert reloaded["positions"] == {}


def _synthetic_df(seed: int, n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    high, low = close * 1.005, close * 0.995
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume}, index=dates)


def test_run_daily_pipeline_writes_auto_trade_state(tmp_path, monkeypatch):
    """End-to-end: run_daily_pipeline() should call the auto-trader and
    persist docs/data/auto_trade_state.json, not just signals_latest.json --
    this is what makes auto-follow keep running without a browser tab open."""
    monkeypatch.setattr(daily_run, "DOCS_DATA_DIR", tmp_path)
    monkeypatch.setattr(daily_run, "WATCHLIST", {"equity": ["SYM"]})
    monkeypatch.setattr(daily_run, "PAIR_WATCHLIST", [])
    monkeypatch.setattr(daily_run, "_load_ohlcv", lambda symbol, asset_class, interval="1d": _synthetic_df(7))

    class _StubSentiment:
        def get_crypto_fear_greed(self):
            return {"value": 50, "classification": "Neutral"}

    class _StubMacro:
        def get_dxy_and_yields_snapshot(self):
            return {}

    monkeypatch.setattr(daily_run, "SentimentProvider", _StubSentiment)
    monkeypatch.setattr(daily_run, "MacroProvider", _StubMacro)
    monkeypatch.setattr(daily_run, "is_market_open", lambda asset_class: True)

    daily_run.run_daily_pipeline()

    state_path = tmp_path / "auto_trade_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert "positions" in state
    assert state["cash"] <= auto_trader.AUTO_TRADER_STARTING_CASH  # either untouched or spent opening a position

    # A second run should load and advance the same state rather than
    # starting over from scratch each time.
    daily_run.run_daily_pipeline()
    second_state = json.loads(state_path.read_text())
    assert len(second_state["equity_history"]) >= len(state["equity_history"])
