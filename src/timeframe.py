from __future__ import annotations

import pandas as pd


def get_daily_context_as_of(daily_df: pd.DataFrame, timestamp) -> dict:
    timestamp_date = pd.Timestamp(timestamp).date()
    prior = daily_df[daily_df["date"] < timestamp_date]
    if prior.empty:
        return {}
    return prior.iloc[-1].to_dict()


def get_completed_intraday_context_as_of(df: pd.DataFrame, timestamp) -> dict:
    prior = df[pd.to_datetime(df["timestamp"]) < pd.Timestamp(timestamp)]
    if prior.empty:
        return {}
    return prior.iloc[-1].to_dict()
