from src.broker.base import Order
from src.broker.paper_broker import PaperBroker
from src.broker import get_broker


def test_paper_broker_buy_and_sell():
    broker = PaperBroker(starting_cash=10_000, commission_bps=0, slippage_bps=0)
    fill = broker.submit_order(Order("AAPL", "buy", 10), market_price=100)
    assert fill.fill_price == 100
    assert broker.positions["AAPL"] == 10
    assert broker.cash == 10_000 - 1000

    broker.submit_order(Order("AAPL", "sell", 10), market_price=110)
    assert broker.positions["AAPL"] == 0
    assert broker.cash == 10_000 - 1000 + 1100


def test_get_broker_defaults_to_paper():
    broker = get_broker("paper")
    assert isinstance(broker, PaperBroker)


def test_get_broker_live_without_keys_raises():
    import pytest
    with pytest.raises(RuntimeError):
        get_broker("live")
