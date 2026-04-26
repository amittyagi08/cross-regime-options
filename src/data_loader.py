from __future__ import annotations

import pandas as pd
import yfinance as yf
import yfinance.cache as yf_cache


REQUIRED_PRICE_COLUMNS = ["date", "open", "high", "low", "close", "volume", "ticker"]
_YFINANCE_CACHE_DISABLED = False


def load_price_history(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    _disable_yfinance_cache()
    data = _download_price_history(ticker, start_date, end_date)
    if data.empty:
        return pd.DataFrame(columns=REQUIRED_PRICE_COLUMNS)

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    normalized = data.reset_index().rename(columns={column: str(column).lower() for column in data.reset_index().columns})
    if "adj close" in normalized.columns:
        normalized = normalized.drop(columns=["adj close"])
    normalized["ticker"] = ticker.upper()

    missing = [column for column in ["close", "volume"] if column not in normalized.columns]
    if missing:
        raise ValueError(f"{ticker} price history missing required columns: {', '.join(missing)}")

    normalized["date"] = pd.to_datetime(normalized["date"]).dt.date
    columns = [column for column in REQUIRED_PRICE_COLUMNS if column in normalized.columns]
    return normalized[columns].dropna(subset=["close", "volume"]).reset_index(drop=True)


def _download_price_history(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    return yf.download(
        ticker,
        start=start_date,
        end=end_date,
        progress=False,
        auto_adjust=False,
        group_by="column",
        threads=False,
    )


def _disable_yfinance_cache() -> None:
    global _YFINANCE_CACHE_DISABLED
    if _YFINANCE_CACHE_DISABLED:
        return
    yf_cache._TzCacheManager._tz_cache = yf_cache._TzCacheDummy()
    yf_cache._CookieCacheManager._Cookie_cache = yf_cache._CookieCacheDummy()
    yf_cache._ISINCacheManager._isin_cache = yf_cache._ISINCacheDummy()
    _YFINANCE_CACHE_DISABLED = True
