from __future__ import annotations

import pandas as pd
import yfinance as yf

from src.data_loader import _disable_yfinance_cache


REQUIRED_INTRADAY_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "ticker"]


def load_intraday_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    _disable_yfinance_cache()
    data = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    if data.empty:
        return pd.DataFrame(columns=REQUIRED_INTRADAY_COLUMNS)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    normalized = data.reset_index().rename(columns={column: str(column).lower() for column in data.reset_index().columns})
    timestamp_col = "datetime" if "datetime" in normalized.columns else normalized.columns[0]
    normalized = normalized.rename(columns={timestamp_col: "timestamp"})
    if "adj close" in normalized.columns:
        normalized = normalized.drop(columns=["adj close"])
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"]).dt.tz_localize(None)
    normalized["ticker"] = ticker.upper()

    missing = [column for column in ["close", "volume"] if column not in normalized.columns]
    if missing:
        raise ValueError(f"{ticker} intraday history missing required columns: {', '.join(missing)}")

    columns = [column for column in REQUIRED_INTRADAY_COLUMNS if column in normalized.columns]
    return normalized[columns].dropna(subset=["close", "volume"]).reset_index(drop=True)
