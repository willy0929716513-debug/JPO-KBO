"""Live crypto exchange broker via CCXT (Binance/Bybit/OKX/Coinbase/...).
DISABLED unless BINANCE_API_KEY / BINANCE_SECRET (or the equivalent for your
chosen exchange) are set -- defaults to PaperBroker otherwise.
"""
from __future__ import annotations

from src.broker.base import Broker, Fill, Order
from src.config import settings


class CCXTBroker(Broker):
    def __init__(self, exchange_id: str = "binance"):
        if not (settings.binance_api_key and settings.binance_secret):
            raise RuntimeError(
                "CCXTBroker requires exchange API credentials to be set. "
                "This system defaults to PaperBroker (fully simulated) until you configure real credentials."
            )
        import ccxt

        self.exchange = getattr(ccxt, exchange_id)({
            "apiKey": settings.binance_api_key,
            "secret": settings.binance_secret,
            "enableRateLimit": True,
        })

    def submit_order(self, order: Order) -> Fill:
        resp = self.exchange.create_order(
            symbol=order.symbol, type=order.order_type, side=order.side,
            amount=order.quantity, price=order.limit_price,
        )
        return Fill(order, float(resp.get("average") or resp.get("price") or 0),
                    float(resp.get("filled") or order.quantity), str(resp.get("timestamp")))

    def get_positions(self) -> dict[str, float]:
        balance = self.exchange.fetch_balance()
        return {k: v for k, v in balance.get("total", {}).items() if v}

    def get_account_equity(self) -> float:
        balance = self.exchange.fetch_balance()
        return float(balance.get("total", {}).get("USDT", 0.0))
