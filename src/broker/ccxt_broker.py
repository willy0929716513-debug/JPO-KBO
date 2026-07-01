"""Live crypto exchange broker via CCXT -- works with any exchange ccxt
supports (Binance, Bybit, OKX, Coinbase, Kraken, Bitget, ...), selected by
`EXCHANGE_ID`. DISABLED unless EXCHANGE_API_KEY / EXCHANGE_API_SECRET are
set -- defaults to PaperBroker otherwise.

Safety defaults:
- `EXCHANGE_USE_TESTNET=true` (default) routes orders to the exchange's
  sandbox/testnet where ccxt supports one, so turning this broker on does
  not touch real funds until you deliberately set it to false.
- Some exchanges (OKX, Coinbase Advanced Trade, ...) require a third
  credential, the API passphrase -- set `EXCHANGE_API_PASSWORD` for those.
"""
from __future__ import annotations

import logging

from src.broker.base import Broker, Fill, Order
from src.config import settings

logger = logging.getLogger(__name__)


class CCXTBroker(Broker):
    def __init__(self, exchange_id: str | None = None):
        if not (settings.exchange_api_key and settings.exchange_api_secret):
            raise RuntimeError(
                "CCXTBroker requires EXCHANGE_API_KEY and EXCHANGE_API_SECRET to be set. "
                "This system defaults to PaperBroker (fully simulated) until you configure real credentials."
            )
        import ccxt

        exchange_id = exchange_id or settings.exchange_id
        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"'{exchange_id}' is not a ccxt-supported exchange id.")

        config = {
            "apiKey": settings.exchange_api_key,
            "secret": settings.exchange_api_secret,
            "enableRateLimit": True,
        }
        if settings.exchange_api_password:
            config["password"] = settings.exchange_api_password

        self.exchange = getattr(ccxt, exchange_id)(config)

        if settings.exchange_use_testnet:
            try:
                self.exchange.set_sandbox_mode(True)
            except Exception as exc:
                logger.warning(
                    "%s does not support ccxt sandbox mode; EXCHANGE_USE_TESTNET has no effect here. "
                    "Set EXCHANGE_USE_TESTNET=false only once you've verified this yourself. (%s)",
                    exchange_id, exc,
                )

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

    def get_account_equity(self, quote_currency: str = "USDT") -> float:
        balance = self.exchange.fetch_balance()
        return float(balance.get("total", {}).get(quote_currency, 0.0))
