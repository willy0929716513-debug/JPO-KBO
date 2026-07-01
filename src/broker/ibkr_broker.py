"""Live/paper broker via Interactive Brokers TWS or IB Gateway, using the
`ib_async` library. Covers global stocks/ETF/futures/forex/options -- the
broadest asset coverage of any adapter in this system.

DISABLED unless `IBKR_ENABLED=true` AND a running TWS or IB Gateway instance
is reachable at `IBKR_HOST:IBKR_PORT`. The default port (7497) is TWS's
*paper* trading port, so simply enabling this without changing the port does
not touch a live account -- you have to deliberately point IBKR_PORT at
7496 (TWS live) or 4001 (IB Gateway live) to trade with real money.

Install with: pip install ib_async
Requires TWS or IB Gateway running locally (or reachable) with the API
enabled (Configuration -> API -> Settings -> Enable ActiveX and Socket Clients).
"""
from __future__ import annotations

from src.broker.base import Broker, Fill, Order
from src.config import settings


class IBKRBroker(Broker):
    def __init__(self):
        if not settings.ibkr_enabled:
            raise RuntimeError(
                "IBKRBroker requires IBKR_ENABLED=true plus a running TWS/IB Gateway instance "
                f"reachable at {settings.ibkr_host}:{settings.ibkr_port}. "
                "This system defaults to PaperBroker (fully simulated) otherwise."
            )
        try:
            from ib_async import IB
        except ImportError as exc:
            raise RuntimeError("Install `ib_async` (pip install ib_async) to use IBKRBroker.") from exc

        self.ib = IB()
        self.ib.connect(settings.ibkr_host, settings.ibkr_port, clientId=settings.ibkr_client_id)

    def submit_order(self, order: Order) -> Fill:
        from ib_async import LimitOrder, MarketOrder, Stock

        contract = Stock(order.symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)

        if order.order_type == "limit" and order.limit_price:
            ib_order = LimitOrder(order.side.upper(), order.quantity, order.limit_price)
        else:
            ib_order = MarketOrder(order.side.upper(), order.quantity)

        trade = self.ib.placeOrder(contract, ib_order)
        self.ib.sleep(1)  # give IBKR a moment to acknowledge/fill

        status = trade.orderStatus
        timestamp = str(trade.log[-1].time) if trade.log else ""
        return Fill(order, float(status.avgFillPrice or 0.0), float(status.filled or 0.0), timestamp)

    def get_positions(self) -> dict[str, float]:
        return {p.contract.symbol: float(p.position) for p in self.ib.positions()}

    def get_account_equity(self) -> float:
        for v in self.ib.accountValues():
            if v.tag == "NetLiquidation" and v.currency == "USD":
                return float(v.value)
        return 0.0

    def disconnect(self) -> None:
        self.ib.disconnect()
