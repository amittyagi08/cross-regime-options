from __future__ import annotations


def get_risk_config(config: dict) -> dict:
    defaults = {
        "enabled": True,
        "stop_loss_pct": -0.18,
        "exit_if_no_followthrough_days": 2,
        "no_followthrough_min_profit_pct": 0.05,
        "pause_after_consecutive_losses": 3,
        "pause_days": 5,
        "max_daily_loss_pct": -0.05,
        "max_weekly_loss_pct": -0.10,
        "cooldown_days_after_ticker_loss": 5,
        "max_trades_per_ticker_per_month": 4,
        "max_open_positions_per_ticker": 1,
        "max_open_positions_per_sector": 2,
        "max_trades_per_sector_per_week": 5,
        "max_sector_capital_pct": 0.50,
        "max_open_positions": 3,
        "max_new_trades_per_day": 3,
        "reduce_size_after_drawdown_pct": -0.08,
        "reduced_position_size_pct": 0.50,
    }
    out = defaults.copy()
    out.update(config.get("risk_controls", {}))
    return out
