from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf


class LiveDataProvider:
    def __init__(self, provider: str = "yahoo"):
        provider = provider.lower()
        if provider != "yahoo":
            raise ValueError("Only yahoo live validation provider is implemented in V5")
        self.provider = provider
        _clear_broken_proxy_env()
        cache_dir = Path("data/cache/yfinance")
        cache_dir.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache_dir))

    def get_price_history(self, ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        data = _download_price_history(ticker, period, interval)
        if not data:
            return pd.DataFrame()
        frame = pd.DataFrame(data)
        frame["date"] = pd.to_datetime(frame["timestamp"], unit="s").dt.date
        frame["ticker"] = ticker.upper()
        return frame

    def get_last_price(self, ticker: str) -> float:
        frame = self.get_price_history(ticker, period="5d", interval="1d")
        if frame.empty:
            return 0.0
        return float(frame["close"].dropna().iloc[-1])

    def get_option_chain(self, ticker: str):
        ticker_obj = yf.Ticker(ticker)
        return ticker_obj.options, ticker_obj

    def get_market_timestamp(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")


def _date_column(frame: pd.DataFrame) -> str:
    for column in ["date", "datetime"]:
        if column in frame.columns:
            return column
    raise ValueError(f"Yahoo price history missing date column. Columns: {', '.join(map(str, frame.columns))}")


def _download_price_history(ticker: str, period: str, interval: str) -> list[dict]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        url,
        params={"range": period, "interval": interval, "includePrePost": "false", "events": "div,splits"},
        timeout=20,
        headers={"User-Agent": "cross-regime-options-live-dashboard/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    chart = payload.get("chart", {})
    errors = chart.get("error")
    if errors:
        raise RuntimeError(f"Yahoo chart error for {ticker}: {errors}")
    results = chart.get("result") or []
    if not results:
        return []

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    adjclose = ((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose", [])
    rows = []
    for index, timestamp in enumerate(timestamps):
        close = _list_get(quote.get("close", []), index)
        if close is None:
            continue
        rows.append(
            {
                "timestamp": timestamp,
                "open": _list_get(quote.get("open", []), index),
                "high": _list_get(quote.get("high", []), index),
                "low": _list_get(quote.get("low", []), index),
                "close": close,
                "adj close": _list_get(adjclose, index),
                "volume": _list_get(quote.get("volume", []), index) or 0,
            }
        )
    return rows


def _list_get(values: list, index: int):
    if index >= len(values):
        return None
    return values[index]


def _clear_broken_proxy_env() -> None:
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        value = os.environ.get(key, "")
        if "127.0.0.1:9" in value or "localhost:9" in value:
            os.environ.pop(key, None)
