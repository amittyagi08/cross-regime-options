import pandas as pd

from src.indicators import add_returns, add_volume_ratio, add_vwap


def test_intraday_vwap_resets_each_day():
    frame = pd.DataFrame(
        [
            {"timestamp": "2026-04-10 09:30", "high": 10, "low": 8, "close": 9, "volume": 100},
            {"timestamp": "2026-04-10 09:35", "high": 12, "low": 10, "close": 11, "volume": 100},
            {"timestamp": "2026-04-11 09:30", "high": 30, "low": 28, "close": 29, "volume": 100},
        ]
    )

    result = add_vwap(frame)

    assert result["vwap"].iloc[0] == 9
    assert result["vwap"].iloc[2] == 29


def test_returns_and_volume_ratio_columns_are_added():
    frame = pd.DataFrame({"close": [10, 11, 12], "volume": [100, 100, 200]})

    result = add_volume_ratio(add_returns(frame, 1), 2)

    assert "return_1" in result.columns
    assert "volume_ratio" in result.columns
    assert result["return_1"].iloc[2] == 12 / 11 - 1
