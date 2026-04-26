from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class BacktestTrade:
    ticker: str
    entry_date: date
    exit_date: date | None
    expiry: str
    strike: float
    right: str
    contracts: int
    entry_underlying_price: float
    exit_underlying_price: float | None
    entry_option_price: float
    exit_option_price: float | None
    entry_delta: float
    entry_theta: float
    exit_reason: str | None
    pnl: float | None
    pnl_pct: float | None
    holding_days: int | None
