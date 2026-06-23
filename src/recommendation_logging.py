from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from src.live.signal_snapshot import LiveSignalSnapshot, OptionSignal
from src.utils import ensure_parent_dir


DEFAULT_DB_PATH = "data/option_alpha.db"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
OPEN = "OPEN"
WATCH = "WATCH"


@dataclass(frozen=True)
class RecommendationRecord:
    timestamp: str
    ticker: str
    sector: str | None
    sector_rank: int | None
    stock_rank: int | None
    option_symbol: str
    expiry: str
    strike: float
    right: str
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    iv: float | None
    oi: int | None
    dte: int | None
    recommendation_score: float
    market_regime: str | None
    recommendation_type: str
    notes: str
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    entry_price: float | None = None
    current_price: float | None = None
    status: str = "WATCH"
    opened_at: str | None = None
    closed_at: str | None = None
    close_price: float | None = None
    close_reason: str | None = None
    pnl: float | None = None
    pnl_pct: float | None = None
    underlying_entry_price: float | None = None
    underlying_current_price: float | None = None
    underlying_return_pct: float | None = None
    latest_notes: str | None = None
    signal_hash: str = ""


def recommendation_db_path(config: dict) -> str:
    return str(config.get("recommendation_logging", {}).get("database_path", DEFAULT_DB_PATH))


def recommendation_logging_enabled(config: dict) -> bool:
    return bool(config.get("recommendation_logging", {}).get("enabled", True))


def initialize_recommendation_db(db_path: str = DEFAULT_DB_PATH) -> None:
    ensure_parent_dir(db_path)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ticker TEXT NOT NULL,
                sector TEXT,
                sector_rank INTEGER,
                stock_rank INTEGER,
                option_symbol TEXT NOT NULL,
                expiry TEXT NOT NULL,
                strike REAL NOT NULL,
                right TEXT NOT NULL,
                delta REAL,
                gamma REAL,
                theta REAL,
                vega REAL,
                iv REAL,
                oi INTEGER,
                dte INTEGER,
                recommendation_score REAL NOT NULL,
                market_regime TEXT,
                recommendation_type TEXT NOT NULL,
                notes TEXT NOT NULL,
                signal_hash TEXT
            )
            """
        )
        _ensure_column(conn, "signal_snapshot", "signal_hash", "TEXT")
        _ensure_column(conn, "signal_snapshot", "bid", "REAL")
        _ensure_column(conn, "signal_snapshot", "ask", "REAL")
        _ensure_column(conn, "signal_snapshot", "mid", "REAL")
        _ensure_column(conn, "signal_snapshot", "entry_price", "REAL")
        _ensure_column(conn, "signal_snapshot", "current_price", "REAL")
        _ensure_column(conn, "signal_snapshot", "status", "TEXT NOT NULL DEFAULT 'WATCH'")
        _ensure_column(conn, "signal_snapshot", "opened_at", "TEXT")
        _ensure_column(conn, "signal_snapshot", "closed_at", "TEXT")
        _ensure_column(conn, "signal_snapshot", "close_price", "REAL")
        _ensure_column(conn, "signal_snapshot", "close_reason", "TEXT")
        _ensure_column(conn, "signal_snapshot", "pnl", "REAL")
        _ensure_column(conn, "signal_snapshot", "pnl_pct", "REAL")
        _ensure_column(conn, "signal_snapshot", "underlying_entry_price", "REAL")
        _ensure_column(conn, "signal_snapshot", "underlying_current_price", "REAL")
        _ensure_column(conn, "signal_snapshot", "underlying_return_pct", "REAL")
        _ensure_column(conn, "signal_snapshot", "latest_notes", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshot_timestamp ON signal_snapshot(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshot_ticker ON signal_snapshot(ticker)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshot_sector ON signal_snapshot(sector)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_snapshot_hash ON signal_snapshot(signal_hash)")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_snapshot_open_idea
            ON signal_snapshot(ticker, option_symbol)
            WHERE status = 'OPEN'
            """
        )


def log_snapshot_recommendations(
    snapshot: LiveSignalSnapshot,
    db_path: str = DEFAULT_DB_PATH,
    config: dict | None = None,
) -> int:
    records = build_recommendation_records(snapshot, config=config)
    if not records:
        initialize_recommendation_db(db_path)
        return 0

    initialize_recommendation_db(db_path)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        records = _downgrade_duplicate_open_records(conn, records)
        rows = [_record_values(record) for record in records]
        before = conn.total_changes
        conn.executemany(
            """
            INSERT INTO signal_snapshot (
                timestamp,
                ticker,
                sector,
                sector_rank,
                stock_rank,
                option_symbol,
                expiry,
                strike,
                right,
                delta,
                gamma,
                theta,
                vega,
                iv,
                oi,
                dte,
                recommendation_score,
                market_regime,
                recommendation_type,
                notes,
                bid,
                ask,
                mid,
                entry_price,
                current_price,
                status,
                opened_at,
                underlying_entry_price,
                underlying_current_price,
                latest_notes,
                signal_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )
        return conn.total_changes - before


def build_recommendation_records(
    snapshot: LiveSignalSnapshot,
    config: dict | None = None,
) -> list[RecommendationRecord]:
    stocks_by_ticker = {stock.ticker: stock for stock in snapshot.universe}
    sectors_by_name = {sector.sector: sector for sector in snapshot.sectors}
    risk_by_ticker = {risk.ticker: risk for risk in snapshot.risk}
    timestamp = snapshot.as_of or datetime.now().astimezone().isoformat(timespec="seconds")

    records = []
    for option in snapshot.options:
        stock = stocks_by_ticker.get(option.ticker)
        sector = sectors_by_name.get(stock.sector) if stock else None
        risk = risk_by_ticker.get(option.ticker)
        recommendation_type = "BUY_CALL" if risk and risk.allowed else "WATCH"
        opens_automatically = _auto_open_paper_trades(config) and not _require_manual_approval(config)
        status = OPEN if recommendation_type == "BUY_CALL" and opens_automatically else REVIEW_REQUIRED if recommendation_type == "BUY_CALL" else WATCH
        record = RecommendationRecord(
            timestamp=timestamp,
            ticker=option.ticker,
            sector=stock.sector if stock else None,
            sector_rank=sector.sector_rank if sector else None,
            stock_rank=stock.stock_rank if stock else None,
            option_symbol=option.contract_symbol,
            expiry=option.expiry,
            strike=float(option.strike),
            right=_right_name(option),
            delta=option.delta,
            gamma=option.gamma,
            theta=option.theta,
            vega=option.vega,
            iv=option.implied_vol,
            oi=option.open_interest,
            dte=option.dte,
            recommendation_score=float(option.total_score),
            market_regime=snapshot.regime_status,
            recommendation_type=recommendation_type,
            notes=_recommendation_notes(option, stock, sector, risk),
            bid=option.bid,
            ask=option.ask,
            mid=option.mid,
            entry_price=option.ask if status == OPEN else None,
            current_price=option.ask if status == OPEN else None,
            status=status,
            opened_at=timestamp if status == OPEN else None,
            underlying_entry_price=stock.last_price if stock and status == OPEN else None,
            underlying_current_price=stock.last_price if stock else None,
            latest_notes=_recommendation_notes(option, stock, sector, risk),
        )
        records.append(RecommendationRecord(**{**record.__dict__, "signal_hash": _signal_hash(record)}))
    return records


def list_recommendations(db_path: str = DEFAULT_DB_PATH, limit: int = 100, ticker: str | None = None) -> list[dict[str, Any]]:
    initialize_recommendation_db(db_path)
    limit = max(1, min(int(limit), 1000))
    params: list[Any] = []
    where = ""
    if ticker:
        where = "WHERE upper(ticker) = upper(?)"
        params.append(ticker)
    params.append(limit)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT *
            FROM signal_snapshot
            {where}
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_recommendation(db_path: str, recommendation_id: int) -> dict[str, Any] | None:
    initialize_recommendation_db(db_path)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM signal_snapshot WHERE id = ?", (recommendation_id,)).fetchone()
    return dict(row) if row else None


def list_open_recommendations(db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    initialize_recommendation_db(db_path)
    return _list_recommendations_by_status(db_path, OPEN)


def list_review_required_recommendations(db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    initialize_recommendation_db(db_path)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM signal_snapshot
            WHERE status = ?
            ORDER BY recommendation_score DESC, timestamp DESC, id DESC
            """,
            (REVIEW_REQUIRED,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_closed_recommendations(db_path: str = DEFAULT_DB_PATH, limit: int = 100) -> list[dict[str, Any]]:
    initialize_recommendation_db(db_path)
    limit = max(1, min(int(limit), 1000))
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM signal_snapshot
            WHERE status IN ('CLOSED', 'EXPIRED')
            ORDER BY closed_at DESC, timestamp DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_open_recommendation_quote(
    db_path: str,
    recommendation_id: int,
    *,
    bid: float | None,
    ask: float | None,
    mid: float | None,
    current_price: float | None,
    underlying_current_price: float | None,
    latest_notes: str | None,
) -> None:
    existing = get_recommendation(db_path, recommendation_id)
    if existing is None:
        return
    pnl, pnl_pct = _pnl(existing.get("entry_price"), current_price)
    underlying_return_pct = _return_pct(existing.get("underlying_entry_price"), underlying_current_price)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            UPDATE signal_snapshot
            SET bid = ?,
                ask = ?,
                mid = ?,
                current_price = ?,
                underlying_current_price = ?,
                underlying_return_pct = ?,
                pnl = ?,
                pnl_pct = ?,
                latest_notes = ?
            WHERE id = ? AND status = 'OPEN'
            """,
            (
                bid,
                ask,
                mid,
                current_price,
                underlying_current_price,
                underlying_return_pct,
                pnl,
                pnl_pct,
                latest_notes,
                recommendation_id,
            ),
        )


def approve_recommendation(
    db_path: str,
    recommendation_id: int,
    *,
    approved_at: str | None = None,
    entry_price: float | None = None,
    latest_notes: str | None = None,
) -> dict[str, Any]:
    initialize_recommendation_db(db_path)
    approved_at = approved_at or datetime.now().astimezone().isoformat(timespec="seconds")
    existing = get_recommendation(db_path, recommendation_id)
    if existing is None:
        raise ValueError("Recommendation not found")
    if existing.get("status") != REVIEW_REQUIRED:
        raise ValueError("Only REVIEW_REQUIRED recommendations can be approved")
    if _active_open_exists(db_path, existing["ticker"], existing["option_symbol"]):
        raise ValueError("An OPEN recommendation already exists for this ticker and contract")

    approved_entry = entry_price if entry_price is not None else existing.get("ask") or existing.get("mid")
    if approved_entry is None or float(approved_entry) <= 0:
        raise ValueError("Approved recommendation needs a positive entry price")

    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            UPDATE signal_snapshot
            SET status = ?,
                opened_at = ?,
                entry_price = ?,
                current_price = ?,
                underlying_entry_price = underlying_current_price,
                latest_notes = COALESCE(?, latest_notes)
            WHERE id = ? AND status = ?
            """,
            (
                OPEN,
                approved_at,
                float(approved_entry),
                float(approved_entry),
                latest_notes,
                recommendation_id,
                REVIEW_REQUIRED,
            ),
        )
    approved = get_recommendation(db_path, recommendation_id)
    if approved is None:
        raise ValueError("Approved recommendation could not be loaded")
    return approved


def close_recommendation(
    db_path: str,
    recommendation_id: int,
    *,
    closed_at: str,
    close_price: float,
    close_reason: str,
    latest_notes: str | None = None,
) -> None:
    existing = get_recommendation(db_path, recommendation_id)
    if existing is None:
        return
    pnl, pnl_pct = _pnl(existing.get("entry_price"), close_price)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            UPDATE signal_snapshot
            SET status = ?,
                closed_at = ?,
                close_price = ?,
                current_price = ?,
                close_reason = ?,
                pnl = ?,
                pnl_pct = ?,
                latest_notes = COALESCE(?, latest_notes)
            WHERE id = ? AND status = 'OPEN'
            """,
            (
                "EXPIRED" if close_reason == "expired" else "CLOSED",
                closed_at,
                close_price,
                close_price,
                close_reason,
                pnl,
                pnl_pct,
                latest_notes,
                recommendation_id,
            ),
        )


def sector_recommendation_counts(db_path: str = DEFAULT_DB_PATH, limit: int = 20) -> list[dict[str, Any]]:
    initialize_recommendation_db(db_path)
    limit = max(1, min(int(limit), 100))
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                COALESCE(sector, 'Unknown') AS sector,
                COUNT(*) AS recommendation_count,
                AVG(recommendation_score) AS average_score,
                MAX(timestamp) AS latest_timestamp
            FROM signal_snapshot
            GROUP BY COALESCE(sector, 'Unknown')
            ORDER BY recommendation_count DESC, average_score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _record_values(record: RecommendationRecord) -> tuple:
    return (
        record.timestamp,
        record.ticker,
        record.sector,
        record.sector_rank,
        record.stock_rank,
        record.option_symbol,
        record.expiry,
        record.strike,
        record.right,
        record.delta,
        record.gamma,
        record.theta,
        record.vega,
        record.iv,
        record.oi,
        record.dte,
        record.recommendation_score,
        record.market_regime,
        record.recommendation_type,
        record.notes,
        record.bid,
        record.ask,
        record.mid,
        record.entry_price,
        record.current_price,
        record.status,
        record.opened_at,
        record.underlying_entry_price,
        record.underlying_current_price,
        record.latest_notes,
        record.signal_hash,
    )


def _downgrade_duplicate_open_records(
    conn: sqlite3.Connection,
    records: list[RecommendationRecord],
) -> list[RecommendationRecord]:
    active_pairs = {
        (str(row[0]).upper(), str(row[1]).upper())
        for row in conn.execute(
            "SELECT ticker, option_symbol FROM signal_snapshot WHERE status = ?",
            (OPEN,),
        ).fetchall()
    }
    output = []
    for record in records:
        pair = (record.ticker.upper(), record.option_symbol.upper())
        if record.status == OPEN and pair in active_pairs:
            output.append(
                replace(
                    record,
                    status=WATCH,
                    entry_price=None,
                    current_price=None,
                    opened_at=None,
                    underlying_entry_price=None,
                    latest_notes=f"Duplicate active open idea already tracked. {record.latest_notes or record.notes}",
                )
            )
        else:
            output.append(record)
            if record.status == OPEN:
                active_pairs.add(pair)
    return output


def _list_recommendations_by_status(db_path: str, status: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM signal_snapshot
            WHERE status = ?
            ORDER BY opened_at DESC, timestamp DESC, id DESC
            """,
            (status,),
        ).fetchall()
    return [dict(row) for row in rows]


def _pnl(entry_price: float | None, current_price: float | None) -> tuple[float | None, float | None]:
    if entry_price is None or current_price is None or entry_price <= 0:
        return None, None
    pnl = float(current_price) - float(entry_price)
    return pnl, pnl / float(entry_price)


def _return_pct(entry_price: float | None, current_price: float | None) -> float | None:
    if entry_price is None or current_price is None or entry_price <= 0:
        return None
    return (float(current_price) - float(entry_price)) / float(entry_price)


def _active_open_exists(db_path: str, ticker: str, option_symbol: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        row = conn.execute(
            """
            SELECT 1
            FROM signal_snapshot
            WHERE upper(ticker) = upper(?)
              AND upper(option_symbol) = upper(?)
              AND status = ?
            LIMIT 1
            """,
            (ticker, option_symbol, OPEN),
        ).fetchone()
    return row is not None


def _auto_open_paper_trades(config: dict | None) -> bool:
    paper = (config or {}).get("paper_trading", {})
    return bool(paper.get("auto_open_paper_trades", paper.get("AUTO_OPEN_PAPER_TRADES", False)))


def _require_manual_approval(config: dict | None) -> bool:
    paper = (config or {}).get("paper_trading", {})
    return bool(paper.get("require_manual_approval", paper.get("REQUIRE_MANUAL_APPROVAL", True)))


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _signal_hash(record: RecommendationRecord) -> str:
    values = [
        record.ticker,
        record.sector,
        record.sector_rank,
        record.stock_rank,
        record.option_symbol,
        record.expiry,
        record.strike,
        record.right,
        record.delta,
        record.gamma,
        record.theta,
        record.vega,
        record.iv,
        record.oi,
        record.dte,
        record.recommendation_score,
        record.market_regime,
        record.recommendation_type,
        record.notes,
    ]
    payload = "|".join(_hash_value(value) for value in values)
    return sha256(payload.encode("utf-8")).hexdigest()


def _hash_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.8f}"
    if value is None:
        return ""
    return str(value)


def _right_name(option: OptionSignal) -> str:
    return "CALL" if option.right.upper() in {"C", "CALL"} else option.right.upper()


def _recommendation_notes(option: OptionSignal, stock, sector, risk) -> str:
    pieces = []
    if sector:
        pieces.append(f"{sector.sector} sector ranked #{sector.sector_rank}")
    if stock:
        pieces.append(f"{stock.ticker} stock rank #{stock.stock_rank}")
    pieces.append(f"option score {option.total_score:.1f}")
    if risk and risk.notes:
        pieces.append(risk.notes)
    elif option.score_details:
        pieces.append(option.score_details)
    return ". ".join(pieces)
