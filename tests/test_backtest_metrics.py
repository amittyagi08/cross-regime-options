from datetime import date

from src.backtest.metrics import calculate_backtest_metrics
from src.backtest.trade import BacktestTrade


def trade_with_pnl(pnl: float, holding_days: int = 3) -> BacktestTrade:
    return BacktestTrade(
        ticker="AAPL",
        entry_date=date(2026, 1, 1),
        exit_date=date(2026, 1, 1 + holding_days),
        expiry="20260130",
        strike=100.0,
        right="C",
        contracts=1,
        entry_underlying_price=100.0,
        exit_underlying_price=101.0,
        entry_option_price=5.0,
        exit_option_price=5.0 + pnl / 100,
        entry_delta=0.60,
        entry_theta=-0.05,
        exit_reason="test",
        pnl=pnl,
        pnl_pct=pnl / 500,
        holding_days=holding_days,
    )


def test_metrics_win_rate_and_profit_factor():
    metrics = calculate_backtest_metrics([trade_with_pnl(100), trade_with_pnl(-50)], 10000)

    assert metrics["total_trades"] == 2
    assert metrics["win_rate"] == 0.5
    assert metrics["profit_factor"] == 2.0


def test_metrics_handle_no_trades():
    metrics = calculate_backtest_metrics([], 10000)

    assert metrics["total_trades"] == 0
    assert metrics["ending_capital"] == 10000
    assert metrics["profit_factor"] == 0.0
