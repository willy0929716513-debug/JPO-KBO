"""Live/paper stock & ETF broker via Alpaca. DISABLED unless
ALPACA_API_KEY / ALPACA_SECRET_KEY are set in the environment -- this file
only ever runs if you deliberately configure real credentials, and even
then Alpaca's own paper-trading endpoint is the default base URL.
"""
from __future__ import annotations

from src.broker.base import Broker, Fill, Order
from src.config import settings


class AlpacaBroker(Broker):
    def __init__(self):
        if not (settings.alpaca_api_key and settings.alpaca_secret_key):
            raise RuntimeError(
                "AlpacaBroker requires ALPACA_API_KEY and ALPACA_SECRET_KEY to be set. "
                "This system defaults to PaperBroker (fully simulated) until you configure real credentials."
            )
        try:
            import alpaca_trade_api as tradeapi
        except ImportError as exc:
            raise RuntimeError("Install `alpaca-trade-api` to use AlpacaBroker.") from exc

        self.api = tradeapi.REST(settings.alpaca_api_key, settings.alpaca_secret_key, settings.alpaca_base_url)

    def submit_order(self, order: Order) -> Fill:
        resp = self.api.submit_order(
            symbol=order.symbol, qty=order.quantity, side=order.side,
            type=order.order_type, time_in_force="day",
            limit_price=order.limit_price,
        )
        return Fill(order, float(resp.filled_avg_price or 0), float(resp.filled_qty or 0), resp.submitted_at)

    def get_positions(self) -> dict[str, float]:
        return {p.symbol: float(p.qty) for p in self.api.list_positions()}

    def get_account_equity(self) -> float:
        return float(self.api.get_account().equity)
