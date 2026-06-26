from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from src.day_trading.intraday_provider import IntradayProvider
from src.day_trading.models import DayTradingSnapshot, MARKET_STATUS_STATES, SIGNAL_STATES
from src.day_trading.scoring import build_ticker_signal, score_market_status
from src.day_trading.yahoo_intraday_provider import YahooIntradayProvider


def build_day_trading_snapshot(config: dict | None = None, provider: IntradayProvider | None = None) -> dict:
    config = config or {}
    day_config = config.get("day_trading", {})
    provider = provider or YahooIntradayProvider()
    market_symbols = list(day_config.get("market_symbols", ["SPY", "QQQ"]))
    watchlist = _watchlist(day_config)
    symbols = _unique_symbols([*market_symbols, *watchlist])
    bars_5m = {symbol: provider.get_intraday_bars(symbol, "5m", "5d") for symbol in symbols}
    bars_1m = {symbol: provider.get_intraday_bars(symbol, "1m", "1d") for symbol in symbols}

    market_rows = [
        score_market_status(symbol, bars_5m.get(symbol, []), bars_1m.get(symbol, []))
        for symbol in market_symbols
    ]
    market_score = _combined_market_score(market_rows)
    market_status = _combined_market_status(market_rows, market_score)
    long_setups = [
        build_ticker_signal(symbol, bars_5m.get(symbol, []), market_score, market_status, "LONG", bars_1m.get(symbol, []))
        for symbol in watchlist
    ]
    short_setups = [
        build_ticker_signal(symbol, bars_5m.get(symbol, []), market_score, market_status, "SHORT", bars_1m.get(symbol, []))
        for symbol in watchlist
    ]
    snapshot = DayTradingSnapshot(
        as_of=datetime.now().astimezone().isoformat(timespec="seconds"),
        provider="yahoo",
        mode="manual_review_only",
        warning=(
            "Yahoo intraday bars are delayed/best-effort research data. "
            "No auto-ordering. Confirm all triggers, quotes, and market status manually."
        ),
        market_status=market_status,
        market_score=round(market_score, 2),
        states=[*MARKET_STATUS_STATES, *SIGNAL_STATES],
        market_rows=market_rows,
        pivot_map=[_pivot_row(row) for row in market_rows],
        long_setups=sorted(long_setups, key=lambda row: row.score, reverse=True),
        short_setups=sorted(short_setups, key=lambda row: row.score, reverse=True),
        active_trades=[],
        closed_trades=[],
        daily_performance={
            "realized_pnl": 0.0,
            "open_risk": 0.0,
            "trades_taken": 0,
            "max_trades_per_day": int(day_config.get("max_trades_per_day", 3)),
            "daily_loss_limit": float(day_config.get("daily_loss_limit", -300.0)),
        },
    )
    return snapshot.to_dict()


def _watchlist(day_config: dict) -> list[str]:
    configured = day_config.get("watchlist")
    if configured:
        return _unique_symbols(configured)
    path = Path(str(day_config.get("watchlist_path", "data/live_watchlist.csv")))
    if path.exists():
        frame = pd.read_csv(path)
        if "ticker" in frame.columns:
            return _unique_symbols(frame["ticker"].dropna().astype(str).tolist())
    return ["NVDA", "AAPL", "MSFT", "AMD", "QQQ"]


def _unique_symbols(symbols) -> list[str]:
    output = []
    for symbol in symbols:
        text = str(symbol).strip().upper()
        if text and text not in output:
            output.append(text)
    return output


def _combined_market_score(rows) -> float:
    valid = [float(row.score) for row in rows if row.last_price is not None]
    if not valid:
        return 50.0
    if len(valid) == 1:
        return valid[0]
    return (valid[0] * 0.55) + (valid[1] * 0.45)


def _combined_market_status(rows, score: float) -> str:
    if any(row.status == "EXTENDED_DO_NOT_CHASE" for row in rows):
        return "EXTENDED_DO_NOT_CHASE"
    if len(rows) >= 2 and rows[0].status in {"LONG_BIAS", "STRONG_LONG"} and rows[1].status in {"SHORT_BIAS", "STRONG_SHORT"}:
        return "MIXED_CHOP"
    if score >= 78:
        return "STRONG_LONG"
    if score >= 58:
        return "LONG_BIAS"
    if score <= 22:
        return "STRONG_SHORT"
    if score <= 42:
        return "SHORT_BIAS"
    return "MIXED_CHOP"


def _pivot_row(row) -> dict:
    pivots = row.pivots
    return {
        "symbol": row.symbol,
        "last_price": row.last_price,
        "pp": pivots.pp,
        "r1": pivots.r1,
        "r2": pivots.r2,
        "r3": pivots.r3,
        "s1": pivots.s1,
        "s2": pivots.s2,
        "s3": pivots.s3,
        "previous_high": pivots.previous_high,
        "previous_low": pivots.previous_low,
        "opening_range_high": pivots.opening_range_high,
        "opening_range_low": pivots.opening_range_low,
    }
