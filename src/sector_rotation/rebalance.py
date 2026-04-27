from __future__ import annotations

import pandas as pd


def get_rebalance_dates(start_date: str, end_date: str, frequency: str = "W-MON") -> list:
    return [timestamp.date() for timestamp in pd.date_range(start=start_date, end=end_date, freq=frequency)]


def get_effective_rebalance_date(price_data: pd.DataFrame, target_date):
    target = pd.Timestamp(target_date).date()
    available = sorted(price_data[price_data["date"] >= target]["date"].unique())
    return available[0] if available else None
