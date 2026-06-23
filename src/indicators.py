from __future__ import annotations

import pandas as pd


def add_ema(df: pd.DataFrame, period: int, price_col: str = "close") -> pd.DataFrame:
    result = df.copy()
    result[f"ema{period}"] = result[price_col].ewm(span=period, adjust=False).mean()
    return result


def add_sma(df: pd.DataFrame, period: int, price_col: str = "close") -> pd.DataFrame:
    result = df.copy()
    result[f"sma{period}"] = result[price_col].rolling(period).mean()
    return result


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    timestamp_col = "timestamp" if "timestamp" in result.columns else "date"
    session = pd.to_datetime(result[timestamp_col]).dt.date
    typical_price = (result["high"] + result["low"] + result["close"]) / 3
    pv = typical_price * result["volume"]
    result["vwap"] = pv.groupby(session).cumsum() / result["volume"].groupby(session).cumsum()
    return result


def add_volume_ratio(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    result = df.copy()
    average_volume = result["volume"].rolling(lookback).mean()
    result["volume_ratio"] = result["volume"] / average_volume
    return result


def add_returns(df: pd.DataFrame, lookback: int, price_col: str = "close") -> pd.DataFrame:
    result = df.copy()
    result[f"return_{lookback}"] = result[price_col] / result[price_col].shift(lookback) - 1
    return result
