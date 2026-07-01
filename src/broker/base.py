"""Broker interface every execution backend implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Order:
    symbol: str
    side: str  # "buy" | "sell"
    quantity: float
    order_type: str = "market"
    limit_price: float | None = None


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
