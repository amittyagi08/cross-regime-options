from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.live.signal_snapshot import LiveSignalSnapshot, OptionSignal
from src.recommendation_logging import (
    OPEN_INITIAL_RISK,
    PARTIAL_PROFIT_TAKEN,
    PROTECTED_BREAKEVEN,
    TRAILING_PROFIT,
    close_recommendation,
    list_open_recommendations,
    record_paper_trade_mark,
    update_open_recommendation_quote,
)


@dataclass(frozen=True)
class LifecycleRefreshResult:
    inspected: int
    updated: int
    closed: int


def refresh_open_recommendations(
    snapshot: LiveSignalSnapshot,
    db_path: str,
    config: dict,
) -> LifecycleRefreshResult:
    open_rows = list_open_recommendations(db_path)
    if not open_rows:
        return LifecycleRefreshResult(inspected=0, updated=0, closed=0)

    options_by_symbol = {option.contract_symbol: option for option in snapshot.options}
    underlying_by_ticker = {stock.ticker: stock.last_price for stock in snapshot.universe}
    as_of = snapshot.as_of or datetime.now().astimezone().isoformat(timespec="seconds")
    updated = 0
    closed = 0

    for row in open_rows:
        option = options_by_symbol.get(row["option_symbol"])
        underlying_current_price = underlying_by_ticker.get(row["ticker"])
        expired, expiry_close_price = _expiry_value(row, underlying_current_price, as_of)
        if expired:
            notes = _lifecycle_notes(row, None, underlying_current_price, "expired")
            close_recommendation(
                db_path,
                int(row["id"]),
                closed_at=as_of,
                close_price=expiry_close_price,
                close_reason="expired",
                latest_notes=notes,
            )
            record_paper_trade_mark(
                db_path,
                int(row["id"]),
                marked_at=as_of,
                bid=None,
                ask=None,
                mid=None,
                current_price=expiry_close_price,
                underlying_current_price=underlying_current_price,
                lifecycle_state="EXITED",
                stop_price=row.get("stop_price"),
                exit_signal="EXIT",
                signal_reason="expired",
                notes=notes,
            )
            closed += 1
            continue

        if option is None:
            continue

        current_price = _current_sell_value(option)
        stop_update = _dynamic_stop_update(row, current_price, config)
        notes = _lifecycle_notes(row, option, underlying_current_price, None)
        update_open_recommendation_quote(
            db_path,
            int(row["id"]),
            bid=option.bid,
            ask=option.ask,
            mid=option.mid,
            current_price=current_price,
            underlying_current_price=underlying_current_price,
            latest_notes=notes,
            lifecycle_state=stop_update["lifecycle_state"],
            high_water_mark=stop_update["high_water_mark"],
            stop_price=stop_update["stop_price"],
            stop_reason=stop_update["stop_reason"],
        )
        updated += 1

        refreshed_row = {**row, **stop_update}
        close_reason = _exit_reason(refreshed_row, current_price, as_of, config)
        record_paper_trade_mark(
            db_path,
            int(row["id"]),
            marked_at=as_of,
            bid=option.bid,
            ask=option.ask,
            mid=option.mid,
            current_price=current_price,
            underlying_current_price=underlying_current_price,
            lifecycle_state=stop_update["lifecycle_state"],
            stop_price=stop_update["stop_price"],
            exit_signal="EXIT" if close_reason else "HOLD",
            signal_reason=close_reason or "hold",
            notes=_lifecycle_notes(row, option, underlying_current_price, close_reason or None),
        )
        if close_reason:
            close_recommendation(
                db_path,
                int(row["id"]),
                closed_at=as_of,
                close_price=current_price,
                close_reason=close_reason,
                latest_notes=_lifecycle_notes(row, option, underlying_current_price, close_reason),
            )
            closed += 1

    return LifecycleRefreshResult(inspected=len(open_rows), updated=updated, closed=closed)


def _current_sell_value(option: OptionSignal) -> float:
    if option.bid is not None and option.bid > 0:
        return float(option.bid)
    if option.mid is not None and option.mid > 0:
        return float(option.mid)
    if option.ask is not None and option.ask > 0:
        return float(option.ask)
    return 0.0


def _exit_reason(row: dict, current_price: float, as_of: str, config: dict) -> str:
    entry_price = row.get("entry_price")
    if entry_price is None or float(entry_price) <= 0:
        return ""

    pnl_pct = (current_price - float(entry_price)) / float(entry_price)
    exit_config = config.get("exit", {})
    if pnl_pct >= float(exit_config.get("profit_target_pct", 0.40)):
        return "profit_target"
    stop_price = row.get("stop_price")
    lifecycle_state = row.get("lifecycle_state")
    if stop_price is not None and current_price <= float(stop_price):
        if lifecycle_state in {TRAILING_PROFIT, PARTIAL_PROFIT_TAKEN}:
            return "trailing_stop"
        if lifecycle_state == PROTECTED_BREAKEVEN:
            return "breakeven_stop"
    if pnl_pct <= float(exit_config.get("stop_loss_pct", -0.25)):
        return "stop_loss"
    if row.get("dte") is not None and int(row["dte"]) <= int(exit_config.get("min_dte_exit", 0)):
        return "min_dte"

    opened_at = _parse_date(str(row.get("opened_at") or row.get("timestamp") or ""))
    current_date = _parse_date(as_of)
    if opened_at and current_date:
        holding_days = (current_date - opened_at).days
        if holding_days >= int(exit_config.get("max_holding_days", 5)):
            return "max_holding_days"

    return ""


def _dynamic_stop_update(row: dict, current_price: float, config: dict) -> dict:
    entry_price = row.get("entry_price")
    if entry_price is None or float(entry_price) <= 0:
        return {
            "lifecycle_state": row.get("lifecycle_state"),
            "high_water_mark": row.get("high_water_mark"),
            "stop_price": row.get("stop_price"),
            "stop_reason": row.get("stop_reason"),
        }

    entry = float(entry_price)
    high_water_mark = max(float(row.get("high_water_mark") or entry), current_price)
    pnl_pct = (current_price - entry) / entry
    exit_config = config.get("exit", {})
    profit_config = config.get("profit_management", {})
    breakeven_trigger = float(exit_config.get("breakeven_trigger_pct", 0.10))
    trailing_trigger = float(exit_config.get("trailing_stop_trigger_pct", 0.20))
    partial_trigger = float(profit_config.get("profit_target_1_pct", 0.40))
    trailing_stop_pct = float(profit_config.get("runner_trailing_stop_pct", exit_config.get("trailing_stop_pct", 0.25)))
    initial_stop = max(0.0, entry * (1.0 + float(exit_config.get("stop_loss_pct", -0.25))))

    lifecycle_state = row.get("lifecycle_state") or OPEN_INITIAL_RISK
    stop_price = float(row.get("stop_price") or initial_stop)
    stop_reason = row.get("stop_reason") or "initial_premium_risk"

    if pnl_pct >= partial_trigger and bool(profit_config.get("sell_half_at_target_1", False)):
        lifecycle_state = PARTIAL_PROFIT_TAKEN
        stop_price = max(entry, high_water_mark * (1.0 - trailing_stop_pct))
        stop_reason = "partial_profit_trailing_stop"
    elif pnl_pct >= trailing_trigger:
        lifecycle_state = TRAILING_PROFIT
        stop_price = max(entry, high_water_mark * (1.0 - trailing_stop_pct))
        stop_reason = "premium_high_water_trailing_stop"
    elif pnl_pct >= breakeven_trigger:
        lifecycle_state = PROTECTED_BREAKEVEN
        stop_price = max(stop_price, entry)
        stop_reason = "breakeven_protection"

    return {
        "lifecycle_state": lifecycle_state,
        "high_water_mark": high_water_mark,
        "stop_price": stop_price,
        "stop_reason": stop_reason,
    }


def _expiry_value(row: dict, underlying_current_price: float | None, as_of: str) -> tuple[bool, float]:
    expiry = _parse_expiry(str(row.get("expiry") or ""))
    current_date = _parse_date(as_of) or date.today()
    if expiry is None or expiry > current_date:
        return False, 0.0
    if underlying_current_price is None:
        return True, 0.0
    strike = float(row.get("strike") or 0.0)
    return True, max(0.0, float(underlying_current_price) - strike)


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return _parse_expiry(value)


def _parse_expiry(value: str) -> date | None:
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _lifecycle_notes(
    row: dict,
    option: OptionSignal | None,
    underlying_current_price: float | None,
    close_reason: str | None,
) -> str:
    entry = row.get("entry_price")
    current = _current_sell_value(option) if option else row.get("current_price")
    premium_note = ""
    if entry is not None and current is not None and float(entry) > 0:
        premium_note = f"Call premium PnL {(float(current) - float(entry)) / float(entry):.1%}."

    underlying_note = ""
    underlying_entry = row.get("underlying_entry_price")
    if underlying_entry is not None and underlying_current_price is not None and float(underlying_entry) > 0:
        underlying_note = (
            f" Underlying moved {(float(underlying_current_price) - float(underlying_entry)) / float(underlying_entry):.1%}."
        )

    greek_note = ""
    if row.get("delta") is not None or row.get("theta") is not None or row.get("iv") is not None:
        greek_note = f" Entry delta {row.get('delta')}, theta {row.get('theta')}, IV {row.get('iv')}."

    reason_note = f" Close reason: {close_reason}." if close_reason else ""
    return f"{premium_note}{underlying_note}{greek_note}{reason_note}".strip()
