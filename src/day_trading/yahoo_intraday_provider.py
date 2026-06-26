from __future__ import annotations

import pandas as pd
import yfinance as yf

from src.day_trading.intraday_provider import IntradayProvider
from src.day_trading.models import IntradayBar


class YahooIntradayProvider(IntradayProvider):
    def get_intraday_bars(self, symbol: str, interval: str = "5m", lookback: str = "1d") -> list[IntradayBar]:
        try:
            raw = yf.Ticker(symbol).history(period=lookback, interval=interval, auto_adjust=False)
        except Exception as exc:
            print(f"[{symbol}] Yahoo intraday bars unavailable: {exc}")
            return []
        if raw is None or raw.empty:
            return []
        frame = raw.rename(columns={column: str(column).lower() for column in raw.columns}).reset_index()
        time_column = _time_column(frame)
        bars: list[IntradayBar] = []
        for row in frame.to_dict("records"):
            close = _safe_float(row.get("close"))
            if close is None:
                continue
            timestamp = row.get(time_column)
            bars.append(
                IntradayBar(
                    symbol=symbol.upper(),
                    timestamp=pd.Timestamp(timestamp).isoformat() if timestamp is not None else "",
                    open=_safe_float(row.get("open")) or close,
                    high=_safe_float(row.get("high")) or close,
                    low=_safe_float(row.get("low")) or close,
                    close=close,
                    volume=_safe_float(row.get("volume")) or 0.0,
                )
            )
        return bars


def _time_column(frame: pd.DataFrame) -> str:
    for column in ("datetime", "date", "index"):
        if column in frame.columns:
            return column
    return str(frame.columns[0])


def _safe_float(value) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
