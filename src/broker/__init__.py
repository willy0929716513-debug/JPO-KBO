from .base import Broker, Fill, Order
from .paper_broker import PaperBroker


def get_broker(mode: str = "paper") -> Broker:
    """Factory that returns PaperBroker unless mode=='live' AND real
    credentials are configured -- live trading is never turned on implicitly."""
    if mode != "live":
        return PaperBroker()
    from src.config import settings
    if settings.alpaca_api_key:
        from src.broker.alpaca_broker import AlpacaBroker
        return AlpacaBroker()
    if settings.binance_api_key:
        from src.broker.ccxt_broker import CCXTBroker
        return CCXTBroker()
    raise RuntimeError("trading_mode=live but no broker credentials configured; refusing to trade with real money.")


__all__ = ["Broker", "Fill", "Order", "PaperBroker", "get_broker"]
