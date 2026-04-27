from __future__ import annotations

from src.backtest.trade import BacktestTrade


def calculate_backtest_metrics(trades: list[BacktestTrade], initial_capital: float) -> dict:
    closed = [trade for trade in trades if trade.pnl is not None]
    if not closed:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "average_pnl": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "average_holding_days": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "ending_capital": initial_capital,
            "return_pct": 0.0,
        }

    pnls = [float(trade.pnl) for trade in closed]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    equity_values = []
    equity = initial_capital
    for pnl in pnls:
        equity += pnl
        equity_values.append(equity)

    total_pnl = sum(pnls)
    return {
        "total_trades": len(closed),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": len(wins) / len(closed),
        "total_pnl": total_pnl,
        "average_pnl": sum(pnls) / len(pnls),
        "average_win": sum(wins) / len(wins) if wins else 0.0,
        "average_loss": sum(losses) / len(losses) if losses else 0.0,
        "profit_factor": gross_profit / abs(gross_loss) if gross_loss else 0.0,
        "max_drawdown": _max_drawdown([initial_capital, *equity_values]),
        "average_holding_days": _average([trade.holding_days or 0 for trade in closed]),
        "best_trade": max(pnls),
        "worst_trade": min(pnls),
        "ending_capital": initial_capital + total_pnl,
        "return_pct": total_pnl / initial_capital if initial_capital else 0.0,
    }


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _max_drawdown(equity_values: list[float]) -> float:
    peak = equity_values[0]
    max_drawdown = 0.0
    for value in equity_values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value - peak)
    return max_drawdown
