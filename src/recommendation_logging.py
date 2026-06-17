from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from src.live.signal_snapshot import LiveSignalSnapshot, OptionSignal
from src.utils import ensure_parent_dir


DEFAULT_DB_PATH = "data/option_alpha.db"


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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshot_timestamp ON signal_snapshot(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshot_ticker ON signal_snapshot(ticker)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshot_sector ON signal_snapshot(sector)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_snapshot_hash ON signal_snapshot(signal_hash)")


def log_snapshot_recommendations(snapshot: LiveSignalSnapshot, db_path: str = DEFAULT_DB_PATH) -> int:
    records = build_recommendation_records(snapshot)
    if not records:
        initialize_recommendation_db(db_path)
        return 0

    initialize_recommendation_db(db_path)
    rows = [_record_values(record) for record in records]
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
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
                signal_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signal_hash) DO NOTHING
            """,
            rows,
        )
        return conn.total_changes - before


def build_recommendation_records(snapshot: LiveSignalSnapshot) -> list[RecommendationRecord]:
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
        record.signal_hash,
    )


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
