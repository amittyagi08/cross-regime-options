from datetime import date, timedelta

from src.backtest.exits import should_exit_trade
from src.backtest.trade import BacktestTrade


CONFIG = {
    "exit": {
        "profit_target_pct": 0.40,
        "stop_loss_pct": -0.25,
        "max_holding_days": 5,
        "exit_on_close_below_ema21": True,
    }
}


def make_trade() -> BacktestTrade:
    return BacktestTrade(
        ticker="AAPL",
        entry_date=date(2026, 1, 1),
        exit_date=None,
        expiry="20260130",
        strike=100.0,
        right="C",
        contracts=1,
        entry_underlying_price=100.0,
        exit_underlying_price=None,
        entry_option_price=5.0,
        exit_option_price=None,
        entry_delta=0.60,
        entry_theta=-0.05,
        exit_reason=None,
        pnl=None,
        pnl_pct=None,
        holding_days=None,
    )


def test_profit_target_triggers():
    should_exit, reason = should_exit_trade(make_trade(), date(2026, 1, 2), 105.0, 7.1, False, CONFIG)

    assert should_exit is True
    assert reason == "profit_target"


def test_stop_loss_triggers():
    should_exit, reason = should_exit_trade(make_trade(), date(2026, 1, 2), 95.0, 3.7, False, CONFIG)

    assert should_exit is True
    assert reason == "stop_loss"


def test_max_holding_days_triggers():
    should_exit, reason = should_exit_trade(make_trade(), date(2026, 1, 6), 100.0, 5.0, False, CONFIG)

    assert should_exit is True
    assert reason == "max_holding_days"


def test_no_exit_when_none_triggered():
    should_exit, reason = should_exit_trade(make_trade(), date(2026, 1, 2), 100.0, 5.2, False, CONFIG)

    assert should_exit is False
    assert reason == ""
