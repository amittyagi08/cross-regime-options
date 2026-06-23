from datetime import date

from src.backtest.trade import BacktestTrade
from src.risk.exposure_controls import can_open_new_trade, get_position_size_multiplier
from src.risk.loss_controls import (
    should_block_ticker_due_to_recent_loss,
    should_exit_no_followthrough,
    should_pause_after_loss_cluster,
)
from src.risk.risk_state import RiskState


def _sample_trade() -> BacktestTrade:
    return BacktestTrade(
        ticker="AAPL",
        entry_date=date(2026, 1, 1),
        exit_date=None,
        expiry="20260201",
        strike=100.0,
        right="C",
        contracts=2,
        entry_underlying_price=100.0,
        exit_underlying_price=None,
        entry_option_price=5.0,
        exit_option_price=None,
        entry_delta=0.6,
        entry_theta=-0.1,
        exit_reason=None,
        pnl=None,
        pnl_pct=None,
        holding_days=None,
    )


def test_loss_cluster_pause_triggers():
    state = RiskState(consecutive_losses=3)
    cfg = {"pause_after_consecutive_losses": 3, "pause_days": 5}

    should_pause, reason = should_pause_after_loss_cluster(state, date(2026, 1, 10), cfg)

    assert should_pause is True
    assert reason in {"loss_cluster_pause", "risk_pause"}
    assert state.pause_until is not None


def test_ticker_cooldown_blocks():
    state = RiskState(ticker_last_loss_date={"AAPL": date(2026, 1, 10)})
    cfg = {"cooldown_days_after_ticker_loss": 5}

    blocked, reason = should_block_ticker_due_to_recent_loss(state, "AAPL", date(2026, 1, 12), cfg)

    assert blocked is True
    assert reason == "ticker_cooldown"


def test_no_followthrough_exit():
    trade = _sample_trade()
    cfg = {"exit_if_no_followthrough_days": 2, "no_followthrough_min_profit_pct": 0.05}

    should_exit, reason = should_exit_no_followthrough(trade, date(2026, 1, 4), 5.1, cfg)

    assert should_exit is True
    assert reason == "no_followthrough"


def test_position_size_reduction():
    cfg = {"reduce_size_after_drawdown_pct": -0.08, "reduced_position_size_pct": 0.50}

    assert get_position_size_multiplier(-0.10, cfg) == 0.50
    assert get_position_size_multiplier(-0.02, cfg) == 1.0


def test_can_open_new_trade_blocks_daily_limit():
    state = RiskState(daily_new_trades={"2026-01-10": 3})
    cfg = {
        "max_new_trades_per_day": 3,
        "max_open_positions": 3,
        "max_open_positions_per_ticker": 1,
        "max_open_positions_per_sector": 2,
        "max_trades_per_ticker_per_month": 4,
        "max_trades_per_sector_per_week": 5,
    }

    allowed, reason = can_open_new_trade("AAPL", "Tech", date(2026, 1, 10), state, [], cfg)

    assert allowed is False
    assert reason == "daily_trade_limit"
