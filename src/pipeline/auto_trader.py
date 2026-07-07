"""Server-side 24/7 paper-trading auto-follower.

The original auto-trade feature (docs/assets/paper.js) only ever runs while
a browser tab with that page open is sitting there -- there's no server to
execute anything when the tab is closed, since this whole site is static
GitHub Pages. This module gives auto-follow an always-on account instead:
it runs once per pipeline execution (already happening every ~5 minutes via
the self-chaining GitHub Actions workflow, 24 hours a day), with its own
persistent virtual portfolio stored in docs/data/auto_trade_state.json and
committed to the repo just like signals_latest.json -- so it keeps trading
regardless of whether anyone has the dashboard open.

The trading *rules* deliberately mirror paperAutoTradeTick()/
paperCheckStopsAndTargets() in docs/assets/paper.js exactly (same per-slot
budget split across every current recommendation, same stop-loss/take-profit
enforcement, same confidence/profit-factor filtering) so the two are directly
comparable as strategies. Per user request, the starting *capital* is
deliberately different between the two accounts (NT$10,000 here vs.
NT$10,000,000 for the browser-local practice account) -- two independent
strategies at two different capital scales, not the same strategy twice.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

AUTO_TRADER_STARTING_CASH = 10_000.0
AUTO_TRADE_NOTIONAL = AUTO_TRADER_STARTING_CASH * 0.1
MAX_HISTORY_ENTRIES = 200
MAX_EQUITY_POINTS = 300

# Per user request: "不要盲目下單，要經過分析考慮" -- don't blindly follow
# every recommendation regardless of how weak or historically unreliable it
# is. Calibrated against real production data rather than picked round: the
# multi-agent decision_engine.confidence for actionable (non-HOLD,
# non-vetoed) signals in this codebase's actual watchlist tops out around
# 0.30 and clusters around 0.16-0.20 (it's a weighted blend across
# technical/macro/risk agents with a low ±0.15 BUY/SELL cutoff, so it
# rarely gets very high) -- a naive "only trade 40-50%+ confidence" bar
# would silently never fire at all. 0.20 filters out the weakest
# borderline cases while still leaving genuinely-actionable signals tradeable.
AUTO_TRADE_MIN_CONFIDENCE = 0.20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_state() -> dict:
    return {
        "cash": AUTO_TRADER_STARTING_CASH,
        "starting_cash": AUTO_TRADER_STARTING_CASH,
        "positions": {},
        "history": [],
        "equity_history": [],
        "realized_pnl": 0.0,
        "realized_pnl_by_symbol": {},
        "trade_stats": {"wins": 0, "losses": 0, "gross_profit": 0.0, "gross_loss": 0.0},
    }


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            import json
            state = json.loads(path.read_text())
            if isinstance(state, dict) and "positions" in state:
                return state
        except Exception:
            pass
    return _empty_state()


def save_state(path: Path, state: dict) -> None:
    import json
    from src.pipeline.daily_run import _json_safe
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(state), indent=2, default=str, allow_nan=False))


def _effective_action(entry: dict) -> str:
    """Mirrors docs/assets/common.js's effectiveAction() exactly -- the true
    multi-agent decision when one exists, falling back to the raw technical
    signal only for entries that predate/lack decision_engine."""
    decision_engine = entry.get("decision_engine")
    if not decision_engine:
        return entry["signal"]["final_action"]
    if decision_engine.get("vetoed"):
        return "HOLD"
    return decision_engine.get("action", "HOLD")


def _effective_confidence(entry: dict) -> float:
    """Mirrors docs/assets/common.js's effectiveConfidence() -- the
    confidence that actually belongs to whatever _effective_action()
    returned, not the raw technical-only confidence."""
    decision_engine = entry.get("decision_engine")
    if not decision_engine:
        return entry["signal"].get("confidence", 0.0)
    if decision_engine.get("vetoed"):
        return 0.0
    return decision_engine.get("confidence", 0.0)


def _dominant_strategy_profit_factor(entry: dict, action: str) -> float | None:
    """Among this symbol's individual strategy votes that agree with the
    direction of `action`, finds whichever strategy is actually driving the
    recommendation (largest weight*confidence) and returns that strategy's
    own historical profit_factor for this exact symbol from backtest_snapshot
    -- so a live BUY/SELL crossing the combined threshold can still be
    skipped if the strategy behind it has a known-bad track record here
    (e.g. mean-reversion on a symbol that's mostly trended for years).
    Returns None when there's not enough information to judge either way
    (never blocks a trade just because backtest data happens to be
    missing/incomplete)."""
    direction = {"BUY": 1, "SELL": -1}.get(action)
    if direction is None:
        return None
    votes = (entry.get("signal") or {}).get("votes") or []
    agreeing = [v for v in votes if {"BUY": 1, "SELL": -1, "HOLD": 0}.get(v.get("action")) == direction]
    if not agreeing:
        return None
    dominant = max(agreeing, key=lambda v: (v.get("weight") or 1.0) * (v.get("confidence") or 0.0))
    metrics = (entry.get("backtest") or {}).get(dominant.get("strategy"))
    return metrics.get("profit_factor") if metrics else None


def _unrealized_pnl(pos: dict, current_price: float | None) -> float:
    if current_price is None:
        return 0.0
    diff = (current_price - pos["avg_price"]) if pos["side"] == "long" else (pos["avg_price"] - current_price)
    return diff * pos["qty"]


def _compute_equity(state: dict, by_symbol: dict) -> float:
    positions_value = sum(pos["avg_price"] * pos["qty"] for pos in state["positions"].values())
    unrealized = sum(
        _unrealized_pnl(pos, (by_symbol.get(symbol) or {}).get("last_price"))
        for symbol, pos in state["positions"].items()
    )
    return state["cash"] + positions_value + unrealized


def _push_history(state: dict, entry: dict) -> None:
    state["history"].insert(0, {"time": _now_iso(), **entry})
    state["history"] = state["history"][:MAX_HISTORY_ENTRIES]


def _close_position(state: dict, symbol: str, price: float, close_reason: str | None) -> None:
    pos = state["positions"].pop(symbol)
    pnl = (price - pos["avg_price"]) * pos["qty"] if pos["side"] == "long" else (pos["avg_price"] - price) * pos["qty"]
    state["cash"] += pos["avg_price"] * pos["qty"] + pnl

    state["realized_pnl"] += pnl
    state["realized_pnl_by_symbol"][symbol] = state["realized_pnl_by_symbol"].get(symbol, 0.0) + pnl
    bucket = "wins" if pnl >= 0 else "losses"
    magnitude_key = "gross_profit" if pnl >= 0 else "gross_loss"
    state["trade_stats"][bucket] += 1
    state["trade_stats"][magnitude_key] += abs(pnl)

    _push_history(state, {
        "symbol": symbol, "side": pos["side"], "action": "close",
        "qty": pos["qty"], "price": price, "pnl": pnl, "close_reason": close_reason,
    })


def run_tick(signals: list[dict], state: dict) -> dict:
    """Advances the always-on auto-trade account by one pipeline cycle:
    enforce stop-loss/take-profit, close positions whose signal flipped
    away, then open a position for every current BUY/SELL recommendation
    not already held (budget split evenly across however many are needed,
    capped at the normal lot size when there's room to spare)."""
    by_symbol = {s["symbol"]: s for s in signals if s.get("last_price") is not None}

    for symbol, pos in list(state["positions"].items()):
        sig = by_symbol.get(symbol)
        if not sig:
            continue
        price = sig["last_price"]
        hit_stop = pos.get("stop_loss") is not None and (
            price <= pos["stop_loss"] if pos["side"] == "long" else price >= pos["stop_loss"]
        )
        hit_target = pos.get("take_profit") is not None and (
            price >= pos["take_profit"] if pos["side"] == "long" else price <= pos["take_profit"]
        )
        if hit_stop or hit_target:
            _close_position(state, symbol, pos["stop_loss"] if hit_stop else pos["take_profit"],
                             "stop_loss" if hit_stop else "take_profit")

    for symbol, pos in list(state["positions"].items()):
        sig = by_symbol.get(symbol)
        if not sig:
            continue
        action = _effective_action(sig)
        want_side = "long" if action == "BUY" else "short" if action == "SELL" else None
        if want_side != pos["side"]:
            _close_position(state, symbol, sig["last_price"], None)

    # Candidate filtering -- "分析考慮，不要盲目下單": a raw BUY/SELL crossing
    # the combined threshold isn't enough on its own. Require (1) confidence
    # above AUTO_TRADE_MIN_CONFIDENCE (skip the weakest borderline calls) and
    # (2) the strategy actually driving the recommendation to have a
    # historically profitable (>=1.0) track record for this exact symbol
    # (skip acting on e.g. mean-reversion where it's a known-bad fit here,
    # even though the combined vote still crossed the action threshold).
    candidates = []
    for s in signals:
        if s.get("last_price") is None or s["symbol"] in state["positions"]:
            continue
        action = _effective_action(s)
        if action not in ("BUY", "SELL"):
            continue
        confidence = _effective_confidence(s)
        if confidence < AUTO_TRADE_MIN_CONFIDENCE:
            continue
        profit_factor = _dominant_strategy_profit_factor(s, action)
        if profit_factor is not None and profit_factor < 1.0:
            continue
        candidates.append((s, action, confidence))

    if candidates:
        # Position size scales with confidence instead of splitting cash
        # flat across every candidate -- a stronger signal earns a bigger
        # bet, a barely-qualifying one gets a smaller bet, both still capped
        # at AUTO_TRADE_NOTIONAL so one very-confident symbol can't swallow
        # the whole account.
        total_confidence = sum(c for _, _, c in candidates)
        available_cash = state["cash"]  # snapshot before the loop -- shares must be
        # computed against a fixed pool, not the live balance, which shrinks as
        # earlier candidates spend it and would otherwise give later candidates
        # in the same batch a shrinking budget regardless of their own confidence.
        for s, action, confidence in candidates:
            price = s["last_price"]
            share = confidence / total_confidence if total_confidence > 0 else 1.0 / len(candidates)
            budget = min(available_cash * share, AUTO_TRADE_NOTIONAL)
            qty = int(budget // price)
            notional = qty * price
            if qty > 0 and notional <= state["cash"]:
                state["cash"] -= notional
                side = "long" if action == "BUY" else "short"
                state["positions"][s["symbol"]] = {
                    "side": side, "qty": qty, "avg_price": price, "opened_at": _now_iso(),
                    "stop_loss": s["signal"].get("stop_loss"), "take_profit": s["signal"].get("take_profit"),
                }
                _push_history(state, {"symbol": s["symbol"], "side": side, "action": "open", "qty": qty, "price": price})

    equity = _compute_equity(state, by_symbol)
    state["equity_history"].append({"time": _now_iso(), "equity": equity})
    state["equity_history"] = state["equity_history"][-MAX_EQUITY_POINTS:]

    return state
