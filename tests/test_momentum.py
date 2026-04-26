import pandas as pd

from src.momentum import calculate_momentum


CONFIG = {
    "strategy": {"min_price": 20},
    "momentum": {"lookback_days": 10, "volume_lookback_days": 10},
}


def test_positive_momentum_returns_signal():
    bars = pd.DataFrame(
        {
            "close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 112],
            "volume": [1000] * 10 + [1500],
        }
    )

    signal = calculate_momentum("AAPL", bars, CONFIG)

    assert signal is not None
    assert signal.ticker == "AAPL"
    assert signal.momentum_score > 0


def test_negative_momentum_returns_none():
    bars = pd.DataFrame(
        {
            "close": [112, 111, 110, 109, 108, 107, 106, 105, 104, 103, 100],
            "volume": [1000] * 11,
        }
    )

    assert calculate_momentum("AAPL", bars, CONFIG) is None


def test_insufficient_data_returns_none():
    bars = pd.DataFrame({"close": [100, 101, 102], "volume": [1000, 1000, 1000]})

    assert calculate_momentum("AAPL", bars, CONFIG) is None
