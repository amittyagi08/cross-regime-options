from __future__ import annotations

from src.backtest.trade import BacktestTrade


def should_take_partial_profit(
    trade: BacktestTrade,
    current_option_price: float,
    config: dict,
) -> tuple[bool, str]:
    if trade.partial_profit_taken:
        return False, ""
    target = float(config.get("profit_target_1_pct", 0.40))
    if trade.entry_option_price <= 0:
        return False, ""
    pnl_pct = (current_option_price - trade.entry_option_price) / trade.entry_option_price
    if pnl_pct >= target:
        return True, "partial_profit"
    return False, ""


def update_runner_trailing_stop(
    trade: BacktestTrade,
    current_option_price: float,
    config: dict,
) -> None:
    if not trade.partial_profit_taken:
        return
    trade.highest_option_price = max(float(trade.highest_option_price or current_option_price), float(current_option_price))
    trailing = float(config.get("runner_trailing_stop_pct", 0.25))
    trade.runner_stop_price = trade.highest_option_price * (1.0 - trailing)


def should_exit_runner(
    trade: BacktestTrade,
    current_option_price: float,
    current_date,
    config: dict,
) -> tuple[bool, str]:
    if not trade.partial_profit_taken:
        return False, ""
    max_days = int(config.get("runner_max_holding_days", 8))
    if (current_date - trade.entry_date).days >= max_days:
        return True, "runner_max_holding"
    if trade.runner_stop_price is not None and current_option_price <= trade.runner_stop_price:
        return True, "runner_trailing_stop"
    return False, ""
