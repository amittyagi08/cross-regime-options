import pandas as pd

from src.timeframe import get_completed_intraday_context_as_of, get_daily_context_as_of


def test_daily_context_uses_prior_completed_day():
    daily = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-09").date(), "close": 100},
            {"date": pd.Timestamp("2026-04-10").date(), "close": 110},
        ]
    )

    context = get_daily_context_as_of(daily, pd.Timestamp("2026-04-10 10:35"))

    assert context["close"] == 100


def test_completed_intraday_context_excludes_current_bar():
    bars = pd.DataFrame(
        [
            {"timestamp": pd.Timestamp("2026-04-10 10:00"), "close": 100},
            {"timestamp": pd.Timestamp("2026-04-10 11:00"), "close": 105},
        ]
    )

    context = get_completed_intraday_context_as_of(bars, pd.Timestamp("2026-04-10 11:00"))

    assert context["close"] == 100
