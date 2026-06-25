from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.live.signal_snapshot import LiveSignalSnapshot, OptionSignal
from src.ultra_short.repository import (
    OPEN,
    OPEN_INITIAL_RISK,
    PROTECTED_BREAKEVEN,
    PROTECTION_MODE,
    TRAILING_PROFIT,
    close_ultra_short_trade,
    list_ultra_short_paper_trades,
    update_ultra_short_trade_mark,
)


@dataclass(frozen=True)
class UltraShortLifecycleResult:
    inspected: int
    marked: int
    closed: int


def refresh_ultra_short_lifecycle(
    snapshot: LiveSignalSnapshot,
    ultra_short_snapshot: dict[str, Any],
    db_path: str,
    config: dict,
) -> UltraShortLifecycleResult:
    trades = list_ultra_short_paper_trades(db_path, state=OPEN, limit=1000)
    if not trades:
        return UltraShortLifecycleResult(inspected=0, marked=0, closed=0)

    options_by_symbol = {option.contract_symbol: option for option in snapshot.options}
    setup_state_by_ticker = _setup_state_by_ticker(ultra_short_snapshot)
    market_mode = str((ultra_short_snapshot.get("market_bias") or {}).get("mode") or "")
    marked_at = snapshot.as_of or datetime.now().astimezone().isoformat(timespec="seconds")
    marked = 0
    closed = 0

    for trade in trades:
        option = options_by_symbol.get(str(trade.get("contract_symbol") or ""))
        current_price = _current_sell_value(option, trade)
        pnl, pnl_pct = _pnl(trade.get("entry_price"), current_price)
        stop_update = _stop_update(trade, current_price, config)
        exit_reason = _exit_reason(
            trade,
            pnl_pct,
            current_price,
            stop_update["stop_price"],
            market_mode,
            setup_state_by_ticker,
            config,
        )
        update_ultra_short_trade_mark(
            db_path,
            trade,
            marked_at=marked_at,
            current_price=current_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            stop_state=stop_update["stop_state"],
            stop_price=stop_update["stop_price"],
            high_water_mark=stop_update["high_water_mark"],
            exit_signal="EXIT" if exit_reason else "HOLD",
            reason=exit_reason or _hold_reason(stop_update["stop_state"], pnl_pct),
        )
        marked += 1
        if exit_reason:
            close_ultra_short_trade(
                db_path,
                trade,
                closed_at=marked_at,
                exit_price=current_price,
                exit_reason=exit_reason,
            )
            closed += 1

    return UltraShortLifecycleResult(inspected=len(trades), marked=marked, closed=closed)


def _setup_state_by_ticker(snapshot: dict[str, Any]) -> dict[tuple[str, str], str]:
    output: dict[tuple[str, str], str] = {}
    for candidate in list(snapshot.get("call_setups") or []) + list(snapshot.get("put_setups") or []):
        ticker = str(candidate.get("ticker") or "")
        direction = str(candidate.get("direction") or "")
        if ticker and direction:
            output[(ticker, direction)] = str(candidate.get("setup_state") or "")
    return output


def _current_sell_value(option: OptionSignal | None, trade: dict[str, Any]) -> float | None:
    if option is not None:
        if option.bid is not None and option.bid > 0:
            return float(option.bid)
        if option.mid is not None and option.mid > 0:
            return float(option.mid)
        if option.ask is not None and option.ask > 0:
            return float(option.ask)
    if trade.get("current_price") is not None:
        return float(trade["current_price"])
    return None


def _stop_update(trade: dict[str, Any], current_price: float | None, config: dict) -> dict[str, float | str | None]:
    entry_price = trade.get("entry_price")
    if entry_price is None or current_price is None or float(entry_price) <= 0:
        return {
            "stop_state": trade.get("stop_state") or OPEN_INITIAL_RISK,
            "stop_price": trade.get("stop_price"),
            "high_water_mark": trade.get("high_water_mark"),
        }

    entry = float(entry_price)
    current = float(current_price)
    high_water = max(float(trade.get("high_water_mark") or entry), current)
    pnl_pct = (current - entry) / entry
    lifecycle = config.get("ultra_short_lifecycle", {})
    protection_trigger = float(lifecycle.get("protection_trigger_pct", 0.10))
    breakeven_trigger = float(lifecycle.get("breakeven_trigger_pct", 0.15))
    trailing_trigger = float(lifecycle.get("trailing_trigger_pct", 0.20))
    trailing_stop_pct = float(lifecycle.get("trailing_stop_pct", 0.20))
    initial_stop_pct = float(lifecycle.get("initial_stop_pct", -0.25))

    stop_state = trade.get("stop_state") or OPEN_INITIAL_RISK
    stop_price = float(trade.get("stop_price") or max(0.0, entry * (1.0 + initial_stop_pct)))

    if pnl_pct >= trailing_trigger:
        stop_state = TRAILING_PROFIT
        stop_price = max(entry, high_water * (1.0 - trailing_stop_pct))
    elif pnl_pct >= breakeven_trigger:
        stop_state = PROTECTED_BREAKEVEN
        stop_price = max(stop_price, entry)
    elif pnl_pct >= protection_trigger:
        stop_state = PROTECTION_MODE
        stop_price = max(stop_price, entry * 0.90)

    return {
        "stop_state": stop_state,
        "stop_price": stop_price,
        "high_water_mark": high_water,
    }


def _exit_reason(
    trade: dict[str, Any],
    pnl_pct: float | None,
    current_price: float | None,
    stop_price: float | None,
    market_mode: str,
    setup_state_by_ticker: dict[tuple[str, str], str],
    config: dict,
) -> str:
    direction = str(trade.get("direction") or "")
    if _market_flipped_against(direction, market_mode):
        return "market_mode_flip"

    setup_state = setup_state_by_ticker.get((str(trade.get("ticker") or ""), direction), "")
    if setup_state == "CHOP_NO_TRADE" or setup_state == "EXTENDED_DO_NOT_CHASE":
        return "vwap_setup_invalidated"

    if current_price is not None and stop_price is not None and float(current_price) <= float(stop_price):
        return "premium_stop"

    stop_loss_pct = float(config.get("ultra_short_lifecycle", {}).get("stop_loss_pct", -0.25))
    profit_target_pct = float(config.get("ultra_short_lifecycle", {}).get("profit_target_pct", 0.35))
    if pnl_pct is not None and pnl_pct <= stop_loss_pct:
        return "stop_loss"
    if pnl_pct is not None and pnl_pct >= profit_target_pct:
        return "profit_target"
    return ""


def _market_flipped_against(direction: str, market_mode: str) -> bool:
    if direction == "CALL":
        return market_mode in {"PUT_BIASED", "PUT_WATCH", "CHOP_NO_TRADE"}
    if direction == "PUT":
        return market_mode in {"CALL_BIASED", "CALL_WATCH", "CHOP_NO_TRADE"}
    return False


def _hold_reason(stop_state: str | None, pnl_pct: float | None) -> str:
    if pnl_pct is None:
        return "hold_no_live_mark"
    return f"hold_{stop_state or OPEN_INITIAL_RISK}"


def _pnl(entry_price: Any, current_price: Any) -> tuple[float | None, float | None]:
    if entry_price is None or current_price is None:
        return None, None
    entry = float(entry_price)
    current = float(current_price)
    if entry <= 0:
        return None, None
    pnl = current - entry
    return pnl, pnl / entry
