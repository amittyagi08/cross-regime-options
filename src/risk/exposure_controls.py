from __future__ import annotations

from src.risk.loss_controls import (
    should_block_due_to_portfolio_loss,
    should_block_ticker_due_to_recent_loss,
)
from src.risk.risk_state import RiskState


def can_open_new_trade(
    ticker: str,
    sector: str,
    current_date,
    risk_state: RiskState,
    open_trades: list,
    config: dict,
) -> tuple[bool, str]:
    del open_trades
    if risk_state.is_paused(current_date):
        return False, "risk_pause"

    blocked, reason = should_block_due_to_portfolio_loss(risk_state, current_date, config)
    if blocked:
        return False, reason

    blocked, reason = should_block_ticker_due_to_recent_loss(risk_state, ticker, current_date, config)
    if blocked:
        return False, reason

    month_key = current_date.strftime("%Y-%m")
    ticker_month_count = risk_state.ticker_monthly_trade_count.get(f"{ticker}:{month_key}", 0)
    if ticker_month_count >= int(config.get("max_trades_per_ticker_per_month", 4)):
        return False, "ticker_monthly_limit"

    week_key = f"{current_date.isocalendar().year}-W{current_date.isocalendar().week:02d}"
    sector_week_count = risk_state.sector_weekly_trade_count.get(f"{sector}:{week_key}", 0)
    if sector_week_count >= int(config.get("max_trades_per_sector_per_week", 5)):
        return False, "sector_weekly_limit"

    if risk_state.open_positions_by_sector.get(sector, 0) >= int(config.get("max_open_positions_per_sector", 2)):
        return False, "sector_open_limit"

    if risk_state.open_positions_by_ticker.get(ticker, 0) >= int(config.get("max_open_positions_per_ticker", 1)):
        return False, "ticker_open_limit"

    if sum(risk_state.open_positions_by_ticker.values()) >= int(config.get("max_open_positions", 3)):
        return False, "portfolio_open_limit"

    day_key = current_date.isoformat()
    if risk_state.daily_new_trades.get(day_key, 0) >= int(config.get("max_new_trades_per_day", 3)):
        return False, "daily_trade_limit"

    return True, ""


def get_position_size_multiplier(
    current_drawdown_pct: float,
    config: dict,
) -> float:
    threshold = float(config.get("reduce_size_after_drawdown_pct", -0.08))
    reduced = float(config.get("reduced_position_size_pct", 0.50))
    if current_drawdown_pct <= threshold:
        return max(0.05, min(1.0, reduced))
    return 1.0
