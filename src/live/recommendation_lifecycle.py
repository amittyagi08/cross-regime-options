from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.live.signal_snapshot import LiveSignalSnapshot, OptionSignal
from src.recommendation_logging import (
    close_recommendation,
    list_open_recommendations,
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
            close_recommendation(
                db_path,
                int(row["id"]),
                closed_at=as_of,
                close_price=expiry_close_price,
                close_reason="expired",
                latest_notes=_lifecycle_notes(row, None, underlying_current_price, "expired"),
            )
            closed += 1
            continue

        if option is None:
            continue

        current_price = _current_sell_value(option)
        update_open_recommendation_quote(
            db_path,
            int(row["id"]),
            bid=option.bid,
            ask=option.ask,
            mid=option.mid,
            current_price=current_price,
            underlying_current_price=underlying_current_price,
            latest_notes=_lifecycle_notes(row, option, underlying_current_price, None),
        )
        updated += 1

        close_reason = _exit_reason(row, current_price, as_of, config)
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
    if pnl_pct <= float(exit_config.get("stop_loss_pct", -0.25)):
        return "stop_loss"

    opened_at = _parse_date(str(row.get("opened_at") or row.get("timestamp") or ""))
    current_date = _parse_date(as_of)
    if opened_at and current_date:
        holding_days = (current_date - opened_at).days
        if holding_days >= int(exit_config.get("max_holding_days", 5)):
            return "max_holding_days"

    return ""


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
