"""Safe, default execution backend: simulates fills against the last known
price with configurable slippage/commission. No real orders are ever sent.
This is what `daily_run.py` and every example in this repo use by default.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.broker.base import Broker, Fill, Order


class PaperBroker(Broker):
    def __init__(self, starting_cash: float = 100_000.0, commission_bps: float = 5.0, slippage_bps: float = 5.0):
        self.cash = starting_cash
        self.commission_bps = commission_bps / 10_000
        self.slippage_bps = slippage_bps / 10_000
        self.positions: dict[str, float] = {}
        self.fills: list[Fill] = []

    def submit_order(self, order: Order, market_price: float | None = None) -> Fill:
        price = market_price if market_price is not None else (order.limit_price or 0.0)
        slip = price * self.slippage_bps * (1 if order.side == "buy" else -1)
        fill_price = price + slip
        commission = abs(fill_price * order.quantity) * self.commission_bps

        signed_qty = order.quantity if order.side == "buy" else -order.quantity
        self.cash -= fill_price * signed_qty + commission
        self.positions[order.symbol] = self.positions.get(order.symbol, 0.0) + signed_qty

        fill = Fill(order, fill_price, order.quantity, datetime.now(timezone.utc).isoformat(), commission)
        self.fills.append(fill)
        return fill

    def get_positions(self) -> dict[str, float]:
        return dict(self.positions)

    def get_account_equity(self, mark_prices: dict[str, float] | None = None) -> float:
        mark_prices = mark_prices or {}
        positions_value = sum(qty * mark_prices.get(sym, 0.0) for sym, qty in self.positions.items())
        return self.cash + positions_value
