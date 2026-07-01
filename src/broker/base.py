"""Broker interface every execution backend implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Order:
    symbol: str
    side: str  # "buy" | "sell"
    quantity: float
    order_type: str = "market"  # "market" | "limit" | "stop" | "stop_limit" | "bracket" | "trailing_stop"
    limit_price: float | None = None
    stop_price: float | None = None            # trigger price for stop / stop_limit orders
    take_profit_price: float | None = None      # bracket order's profit-take leg
    stop_loss_price: float | None = None        # bracket order's stop-loss leg
    trail_amount: float | None = None           # trailing_stop: absolute distance the stop trails by
    time_in_force: str = "day"                  # "day" | "gtc" | "ioc" | "fok"

    def is_bracket(self) -> bool:
        return self.take_profit_price is not None or self.stop_loss_price is not None


@dataclass
class Fill:
    order: Order
    fill_price: float
    fill_quantity: float
    timestamp: str
    commission: float = 0.0


class Broker(ABC):
    @abstractmethod
    def submit_order(self, order: Order) -> Fill:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> dict[str, float]:
        raise NotImplementedError

    @abstractmethod
    def get_account_equity(self) -> float:
        raise NotImplementedError
