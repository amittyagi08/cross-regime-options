from __future__ import annotations

from datetime import timedelta

from src.backtest.trade import BacktestTrade
from src.risk.risk_state import RiskState


def should_pause_after_loss_cluster(
    risk_state: RiskState,
    current_date,
    config: dict,
) -> tuple[bool, str]:
    threshold = int(config.get("pause_after_consecutive_losses", 3))
    pause_days = int(config.get("pause_days", 5))
    if risk_state.consecutive_losses < threshold:
        return False, ""
    if risk_state.pause_until is None or current_date > risk_state.pause_until:
        risk_state.pause_until = current_date + timedelta(days=pause_days)
        return True, "loss_cluster_pause"
    return risk_state.is_paused(current_date), "risk_pause" if risk_state.is_paused(current_date) else ""


def should_block_due_to_portfolio_loss(
    risk_state: RiskState,
    current_date,
    config: dict,
) -> tuple[bool, str]:
    daily = float(risk_state.daily_pnl.get(current_date.isoformat(), 0.0))
    week_key = f"{current_date.isocalendar().year}-W{current_date.isocalendar().week:02d}"
    weekly = float(risk_state.weekly_pnl.get(week_key, 0.0))
    if daily <= float(config.get("max_daily_loss_pct", -0.05)):
        return True, "daily_loss_limit"
    if weekly <= float(config.get("max_weekly_loss_pct", -0.10)):
        return True, "weekly_loss_limit"
    return False, ""


def should_block_ticker_due_to_recent_loss(
    risk_state: RiskState,
    ticker: str,
    current_date,
    config: dict,
) -> tuple[bool, str]:
    last = risk_state.ticker_last_loss_date.get(ticker)
    if last is None:
        return False, ""
    cooldown = int(config.get("cooldown_days_after_ticker_loss", 5))
    if (current_date - last).days < cooldown:
        return True, "ticker_cooldown"
    return False, ""


def should_exit_no_followthrough(
    trade: BacktestTrade,
    current_date,
    current_option_price: float,
    config: dict,
) -> tuple[bool, str]:
    holding_days = (current_date - trade.entry_date).days
    min_days = int(config.get("exit_if_no_followthrough_days", 2))
    min_profit = float(config.get("no_followthrough_min_profit_pct", 0.05))
    if holding_days < min_days:
        return False, ""
    entry = float(trade.entry_option_price)
    if entry <= 0:
        return False, ""
    pnl_pct = (float(current_option_price) - entry) / entry
    if pnl_pct < min_profit:
        return True, "no_followthrough"
    return False, ""
