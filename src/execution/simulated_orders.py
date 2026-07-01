"""Simulated advanced order types: bracket (entry + take-profit + stop-loss),
OCO (one-cancels-other), and trailing stop. These operate on a historical or
streamed OHLC price series to determine *when and at what price* the order
would actually have been filled -- useful both for realistic backtesting of
exit logic and, live, for brokers/exchanges that don't natively support the
order type (submit a market/limit order now, then poll price bars and call
these to decide when to submit the actual exit order).

None of this talks to a real broker; `src/broker/*` handles actual order
submission once these functions decide *what* to submit.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class ExecutionResult:
    triggered: bool
    trigger_type: str | None  # "take_profit" | "stop_loss" | "time_limit" | None (never triggered)
    exit_price: float | None
    exit_time: object | None
    bars_held: int


def simulate_bracket_order(
    bars: pd.DataFrame, entry_price: float, direction: int,
    take_profit: float | None, stop_loss: float | None, max_bars: int | None = None,
) -> ExecutionResult:
    """Walks forward through `bars` (OHLC, starting *after* entry) and finds
    whichever of take-profit / stop-loss / max_bars time-limit is hit first.
    `direction`: 1 = long (exit when high >= take_profit or low <= stop_loss),
    -1 = short (mirrored). Checks stop-loss before take-profit within a bar
    when both could plausibly trigger (conservative assumption, since we
    don't know intra-bar path from OHLC alone).
    """
    window = bars if max_bars is None else bars.iloc[:max_bars]

    for i, (ts, row) in enumerate(window.iterrows(), start=1):
        if direction == 1:
            if stop_loss is not None and row["low"] <= stop_loss:
                return ExecutionResult(True, "stop_loss", float(stop_loss), ts, i)
            if take_profit is not None and row["high"] >= take_profit:
                return ExecutionResult(True, "take_profit", float(take_profit), ts, i)
        else:
            if stop_loss is not None and row["high"] >= stop_loss:
                return ExecutionResult(True, "stop_loss", float(stop_loss), ts, i)
            if take_profit is not None and row["low"] <= take_profit:
                return ExecutionResult(True, "take_profit", float(take_profit), ts, i)

    if len(window) == 0:
        return ExecutionResult(False, None, None, None, 0)
    last_ts, last_row = window.index[-1], window.iloc[-1]
    return ExecutionResult(True, "time_limit", float(last_row["close"]), last_ts, len(window))


def simulate_oco_order(
    bars: pd.DataFrame, level_a: float, level_b: float, max_bars: int | None = None,
) -> ExecutionResult:
    """One-Cancels-the-Other: two resting orders at `level_a` and `level_b`
    (e.g. a limit sell above the market and a stop sell below it); whichever
    price level is touched first fills and the other is implicitly cancelled.
    Level order doesn't matter -- whichever the price reaches first wins.
    """
    hi, lo = max(level_a, level_b), min(level_a, level_b)
    window = bars if max_bars is None else bars.iloc[:max_bars]

    for i, (ts, row) in enumerate(window.iterrows(), start=1):
        touched_hi = row["high"] >= hi
        touched_lo = row["low"] <= lo
        if touched_hi and touched_lo:
            # Both levels touched within the same bar and OHLC alone can't tell us
            # which came first -- conservatively assume the worse-for-the-trade one.
            return ExecutionResult(True, "ambiguous_both_touched", float(lo), ts, i)
        if touched_hi:
            return ExecutionResult(True, "level_a" if level_a == hi else "level_b", float(hi), ts, i)
        if touched_lo:
            return ExecutionResult(True, "level_a" if level_a == lo else "level_b", float(lo), ts, i)

    return ExecutionResult(False, None, None, None, 0)


def simulate_trailing_stop(
    bars: pd.DataFrame, entry_price: float, direction: int, trail_amount: float, max_bars: int | None = None,
) -> ExecutionResult:
    """direction: 1 = long (stop trails below the running high by
    `trail_amount`), -1 = short (stop trails above the running low)."""
    window = bars if max_bars is None else bars.iloc[:max_bars]

    if direction == 1:
        stop = entry_price - trail_amount
        running_extreme = entry_price
        for i, (ts, row) in enumerate(window.iterrows(), start=1):
            if row["low"] <= stop:
                return ExecutionResult(True, "trailing_stop", float(stop), ts, i)
            running_extreme = max(running_extreme, row["high"])
            stop = max(stop, running_extreme - trail_amount)
    else:
        stop = entry_price + trail_amount
        running_extreme = entry_price
        for i, (ts, row) in enumerate(window.iterrows(), start=1):
            if row["high"] >= stop:
                return ExecutionResult(True, "trailing_stop", float(stop), ts, i)
            running_extreme = min(running_extreme, row["low"])
            stop = min(stop, running_extreme + trail_amount)

    if len(window) == 0:
        return ExecutionResult(False, None, None, None, 0)
    last_ts, last_row = window.index[-1], window.iloc[-1]
    return ExecutionResult(True, "time_limit", float(last_row["close"]), last_ts, len(window))
