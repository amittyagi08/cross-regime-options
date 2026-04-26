from __future__ import annotations

from datetime import date

from src.backtest.trade import BacktestTrade


def should_exit_trade(
    trade: BacktestTrade,
    current_date: date,
    current_underlying_price: float,
    current_option_price: float,
    current_close_below_ema21: bool,
    config: dict,
) -> tuple[bool, str]:
    del current_underlying_price
    exit_config = config.get("exit", {})
    basis = trade.entry_option_price * 100 * trade.contracts
    current_value = current_option_price * 100 * trade.contracts
    pnl_pct = (current_value - basis) / basis if basis > 0 else 0.0
    holding_days = (current_date - trade.entry_date).days

    if pnl_pct >= float(exit_config.get("profit_target_pct", 0.40)):
        return True, "profit_target"
    if pnl_pct <= float(exit_config.get("stop_loss_pct", -0.25)):
        return True, "stop_loss"
    if holding_days >= int(exit_config.get("max_holding_days", 5)):
        return True, "max_holding_days"
    if bool(exit_config.get("exit_on_close_below_ema21", True)) and current_close_below_ema21:
        return True, "close_below_ema21"

    return False, ""
