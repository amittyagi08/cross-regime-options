import pandas as pd

from src.backtest.multi_timeframe_engine import (
    MultiTimeframeSyntheticOptionsBacktestEngine,
    _position_size_multiplier,
)


CONFIG = {
    "daily_filter": {"min_daily_momentum_score": 0.04},
    "timeframe_60m": {
        "enabled": True,
        "momentum_lookback_bars": 6,
        "avoid_if_extended_from_ema21_pct": 0.06,
    },
    "timeframe_5m": {
        "enabled": True,
        "breakout_lookback_bars": 2,
        "min_5m_return": 0.003,
        "min_volume_ratio": 1.2,
    },
    "mtf_scoring": {
        "entry_threshold": 60,
        "full_size_threshold": 75,
        "half_size_multiplier": 0.5,
    },
}


def test_position_size_multiplier_uses_score_bands():
    assert _position_size_multiplier(80, CONFIG) == 1.0
    assert _position_size_multiplier(60, CONFIG) == 0.5
    assert _position_size_multiplier(59, CONFIG) == 0.0


def test_sixty_minute_score_awards_components():
    engine = MultiTimeframeSyntheticOptionsBacktestEngine(CONFIG)
    context = {"close": 105.0, "ema21": 100.0, "return_6": 0.01}

    assert engine._sixty_minute_score(context) == 30


def test_five_minute_score_awards_breakout_and_volume():
    engine = MultiTimeframeSyntheticOptionsBacktestEngine(CONFIG)
    bars = pd.DataFrame(
        [
            {"high": 10, "close": 10.0, "vwap": 9.5, "volume_ratio": 1.0, "return_2": 0.0},
            {"high": 10.5, "close": 10.2, "vwap": 10.4, "volume_ratio": 1.0, "return_2": 0.0},
            {"high": 10.8, "close": 11.0, "vwap": 10.6, "volume_ratio": 1.3, "return_2": 0.10},
        ]
    )

    assert engine._five_minute_score(bars, 2) == 30
