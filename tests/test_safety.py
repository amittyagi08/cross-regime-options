import pytest

from src.ibkr_client import IBKRClient


def test_order_submission_is_disabled():
    client = IBKRClient("127.0.0.1", 7497, 11)

    with pytest.raises(RuntimeError, match="Order submission is disabled"):
        client.ib.placeOrder(None, None)
