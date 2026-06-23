from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


@dataclass
class RiskState:
    consecutive_losses: int = 0
    pause_until: Optional[date] = None
    daily_pnl: Dict[str, float] = field(default_factory=dict)
    weekly_pnl: Dict[str, float] = field(default_factory=dict)
    ticker_last_loss_date: Dict[str, date] = field(default_factory=dict)
    ticker_monthly_trade_count: Dict[str, int] = field(default_factory=dict)
    sector_weekly_trade_count: Dict[str, int] = field(default_factory=dict)
    open_positions_by_sector: Dict[str, int] = field(default_factory=dict)
    open_positions_by_ticker: Dict[str, int] = field(default_factory=dict)
    risk_events: List[dict] = field(default_factory=list)
    daily_new_trades: Dict[str, int] = field(default_factory=dict)
    _last_week: Optional[str] = None
    _last_month: Optional[str] = None

    def record_trade_open(self, ticker: str, sector: str | None, opened_on: date) -> None:
        day_key = opened_on.isoformat()
        self.daily_new_trades[day_key] = self.daily_new_trades.get(day_key, 0) + 1
        month_key = opened_on.strftime("%Y-%m")
        self.ticker_monthly_trade_count[f"{ticker}:{month_key}"] = self.ticker_monthly_trade_count.get(f"{ticker}:{month_key}", 0) + 1
        week_key = f"{opened_on.isocalendar().year}-W{opened_on.isocalendar().week:02d}"
        if sector:
            self.sector_weekly_trade_count[f"{sector}:{week_key}"] = self.sector_weekly_trade_count.get(f"{sector}:{week_key}", 0) + 1
            self.open_positions_by_sector[sector] = self.open_positions_by_sector.get(sector, 0) + 1
        self.open_positions_by_ticker[ticker] = self.open_positions_by_ticker.get(ticker, 0) + 1

    def record_trade_close(self, ticker: str, sector: str | None, closed_on: date, pnl: float) -> None:
        day_key = closed_on.isoformat()
        self.daily_pnl[day_key] = self.daily_pnl.get(day_key, 0.0) + float(pnl)
        week_key = f"{closed_on.isocalendar().year}-W{closed_on.isocalendar().week:02d}"
        self.weekly_pnl[week_key] = self.weekly_pnl.get(week_key, 0.0) + float(pnl)

        if pnl < 0:
            self.consecutive_losses += 1
            self.ticker_last_loss_date[ticker] = closed_on
        else:
            self.consecutive_losses = 0

        self.open_positions_by_ticker[ticker] = max(0, self.open_positions_by_ticker.get(ticker, 0) - 1)
        if sector:
            self.open_positions_by_sector[sector] = max(0, self.open_positions_by_sector.get(sector, 0) - 1)

    def record_risk_event(self, **event) -> None:
        self.risk_events.append(event)

    def is_paused(self, current_date: date) -> bool:
        return self.pause_until is not None and current_date <= self.pause_until

    def reset_weekly_counters_if_needed(self, current_date: date) -> None:
        week_key = f"{current_date.isocalendar().year}-W{current_date.isocalendar().week:02d}"
        if self._last_week == week_key:
            return
        self._last_week = week_key
        self.sector_weekly_trade_count = {k: v for k, v in self.sector_weekly_trade_count.items() if k.endswith(week_key)}

    def reset_monthly_counters_if_needed(self, current_date: date) -> None:
        month_key = current_date.strftime("%Y-%m")
        if self._last_month == month_key:
            return
        self._last_month = month_key
        self.ticker_monthly_trade_count = {k: v for k, v in self.ticker_monthly_trade_count.items() if k.endswith(month_key)}
