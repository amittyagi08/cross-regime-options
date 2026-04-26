import pytest

from src.ibkr_client import _empty_market_data, _market_data_type_id


def test_market_data_type_names_map_to_ibkr_ids():
    assert _market_data_type_id("live") == 1
    assert _market_data_type_id("frozen") == 2
    assert _market_data_type_id("delayed") == 3
    assert _market_data_type_id("delayed_frozen") == 4


def test_invalid_market_data_type_raises():
    with pytest.raises(ValueError, match="Invalid market data type"):
        _market_data_type_id("bad")


def test_empty_market_data_has_expected_keys():
    data = _empty_market_data("delayed_frozen", "IBKR error 10091")

    assert data["market_data_type"] == "delayed_frozen"
    assert data["market_data_error"] == "IBKR error 10091"
    assert data["bid"] is None
    assert data["delta"] is None
