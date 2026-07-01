"""TWAP / VWAP / POV execution-algorithm simulation: slices a large parent
order into child orders spread over time, then measures execution quality
(average fill price vs. arrival price and vs. the TWAP/VWAP benchmark --
i.e. implementation shortfall and slippage) against a historical intrabar
price/volume series. Useful for sizing how much a large order would move
the market and for comparing execution styles before actually trading.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class ExecutionReport:
    algo: str
    side: str
    total_quantity: float
    avg_fill_price: float
    arrival_price: float
    benchmark_price: float
    slippage_vs_arrival_bps: float
    slippage_vs_benchmark_bps: float
    child_fills: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "algo": self.algo, "side": self.side, "total_quantity": self.total_quantity,
            "avg_fill_price": round(self.avg_fill_price, 6), "arrival_price": round(self.arrival_price, 6),
            "benchmark_price": round(self.benchmark_price, 6),
            "slippage_vs_arrival_bps": round(self.slippage_vs_arrival_bps, 2),
            "slippage_vs_benchmark_bps": round(self.slippage_vs_benchmark_bps, 2),
            "num_child_orders": len(self.child_fills),
        }


def twap_schedule(total_quantity: float, num_slices: int) -> list[float]:
    """Equal-sized child order quantities, one per time slice."""
    if num_slices <= 0:
        return [total_quantity]
    base = total_quantity / num_slices
    return [base] * num_slices


def vwap_schedule(total_quantity: float, historical_volume_profile: pd.Series) -> pd.Series:
    """Child order quantities proportional to a historical intraday volume
    profile (e.g. average volume per bar over the last N days), so larger
    slices execute when the market is naturally more liquid."""
    weights = historical_volume_profile / historical_volume_profile.sum()
    return weights * total_quantity


def simulate_twap_execution(
    bars: pd.DataFrame, total_quantity: float, side: str, num_slices: int | None = None,
) -> ExecutionReport:
    """Splits `total_quantity` evenly across every bar in `bars` (one slice
    per bar unless `num_slices` is given, in which case it uses the first
    `num_slices` bars), filling each slice at that bar's close."""
    window = bars if num_slices is None else bars.iloc[:num_slices]
    if window.empty:
        raise ValueError("No bars to execute against.")

    quantities = twap_schedule(total_quantity, len(window))
    fills = [{"time": str(ts), "price": float(row["close"]), "quantity": q}
             for (ts, row), q in zip(window.iterrows(), quantities)]

    arrival_price = float(bars.iloc[0]["open"])
    twap_benchmark = float(window["close"].mean())
    avg_fill = float(np.average([f["price"] for f in fills], weights=[f["quantity"] for f in fills]))

    direction = 1 if side == "buy" else -1
    slip_arrival = direction * (avg_fill - arrival_price) / arrival_price * 10_000
    slip_benchmark = direction * (avg_fill - twap_benchmark) / twap_benchmark * 10_000

    return ExecutionReport("TWAP", side, total_quantity, avg_fill, arrival_price, twap_benchmark,
                            slip_arrival, slip_benchmark, fills)


def simulate_vwap_execution(bars: pd.DataFrame, total_quantity: float, side: str) -> ExecutionReport:
    """Splits `total_quantity` proportionally to each bar's own volume
    (a simple same-day VWAP participation approach), filling each slice at
    that bar's close."""
    if bars.empty:
        raise ValueError("No bars to execute against.")

    quantities = vwap_schedule(total_quantity, bars["volume"].clip(lower=1e-9))
    fills = [{"time": str(ts), "price": float(row["close"]), "quantity": float(q)}
             for (ts, row), q in zip(bars.iterrows(), quantities)]

    arrival_price = float(bars.iloc[0]["open"])
    vwap_benchmark = float((bars["close"] * bars["volume"]).sum() / bars["volume"].sum())
    avg_fill = float(np.average([f["price"] for f in fills], weights=[f["quantity"] for f in fills]))

    direction = 1 if side == "buy" else -1
    slip_arrival = direction * (avg_fill - arrival_price) / arrival_price * 10_000
    slip_benchmark = direction * (avg_fill - vwap_benchmark) / vwap_benchmark * 10_000

    return ExecutionReport("VWAP", side, total_quantity, avg_fill, arrival_price, vwap_benchmark,
                            slip_arrival, slip_benchmark, fills)


def simulate_pov_execution(
    bars: pd.DataFrame, total_quantity: float, side: str, participation_rate: float = 0.1,
) -> ExecutionReport:
    """Percent-of-Volume: each slice is capped at `participation_rate` of
    that bar's volume, continuing across bars until fully filled (or bars
    run out). Approximates how a real POV algo limits market impact."""
    if bars.empty:
        raise ValueError("No bars to execute against.")

    remaining = total_quantity
    fills = []
    filled_index = []
    for ts, row in bars.iterrows():
        if remaining <= 1e-9:
            break
        slice_qty = min(remaining, row["volume"] * participation_rate)
        if slice_qty <= 0:
            continue
        fills.append({"time": str(ts), "price": float(row["close"]), "quantity": float(slice_qty)})
        filled_index.append(ts)
        remaining -= slice_qty

    if not fills:
        raise ValueError("Could not fill any quantity at the given participation rate within the provided bars.")

    arrival_price = float(bars.iloc[0]["open"])
    filled_bars = bars.loc[filled_index]
    benchmark = float((filled_bars["close"] * filled_bars["volume"]).sum() / filled_bars["volume"].sum())
    avg_fill = float(np.average([f["price"] for f in fills], weights=[f["quantity"] for f in fills]))

    direction = 1 if side == "buy" else -1
    slip_arrival = direction * (avg_fill - arrival_price) / arrival_price * 10_000
    slip_benchmark = direction * (avg_fill - benchmark) / benchmark * 10_000

    report = ExecutionReport("POV", side, sum(f["quantity"] for f in fills), avg_fill, arrival_price, benchmark,
                              slip_arrival, slip_benchmark, fills)
    return report
