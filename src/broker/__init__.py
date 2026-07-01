from .base import Broker, Fill, Order
from .paper_broker import PaperBroker


def get_broker(mode: str = "paper", asset_class: str | None = None) -> Broker:
    """Factory that returns PaperBroker unless mode=='live' AND real
    credentials are configured for the requested asset class -- live
    trading is never turned on implicitly.

    `asset_class` picks which live adapter to try first:
      - "crypto"            -> CCXTBroker (Binance/Bybit/OKX/Coinbase/... via EXCHANGE_ID)
      - "equity"/"etf"/None -> AlpacaBroker, falling back to IBKRBroker
      - anything else (forex/futures/options/global markets) -> IBKRBroker

    Every adapter independently refuses to construct without its own
    credentials/connection configured, so an incomplete .env safely falls
    through to the RuntimeError below rather than trading by accident.
    """
    if mode != "live":
        return PaperBroker()

    from src.config import settings

    if asset_class == "crypto":
        if settings.exchange_api_key and settings.exchange_api_secret:
            from src.broker.ccxt_broker import CCXTBroker
            return CCXTBroker(settings.exchange_id)
        raise RuntimeError(
            f"trading_mode=live for asset_class=crypto but EXCHANGE_API_KEY/EXCHANGE_API_SECRET "
            f"are not set for exchange '{settings.exchange_id}'; refusing to trade with real money."
        )

    if asset_class in (None, "equity", "etf"):
        if settings.alpaca_api_key and settings.alpaca_secret_key:
            from src.broker.alpaca_broker import AlpacaBroker
            return AlpacaBroker()
        if settings.ibkr_enabled:
            from src.broker.ibkr_broker import IBKRBroker
            return IBKRBroker()

    if asset_class in ("forex", "futures", "metal", "energy") and settings.ibkr_enabled:
        from src.broker.ibkr_broker import IBKRBroker
        return IBKRBroker()

    raise RuntimeError(
        f"trading_mode=live (asset_class={asset_class!r}) but no matching broker credentials are "
        "configured (Alpaca / IBKR / an EXCHANGE_ID exchange); refusing to trade with real money."
    )


__all__ = ["Broker", "Fill", "Order", "PaperBroker", "get_broker"]
