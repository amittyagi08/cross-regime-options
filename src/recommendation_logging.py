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
SUPERSEDED = "SUPERSEDED"
REJECTED = "REJECTED"
OPEN_INITIAL_RISK = "OPEN_INITIAL_RISK"
PROTECTED_BREAKEVEN = "PROTECTED_BREAKEVEN"
TRAILING_PROFIT = "TRAILING_PROFIT"
PARTIAL_PROFIT_TAKEN = "PARTIAL_PROFIT_TAKEN"
EXITED = "EXITED"


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
    signal_date: str | None = None
    candidate_key: str | None = None
    lifecycle_state: str | None = None
    high_water_mark: float | None = None
    stop_price: float | None = None
    stop_reason: str | None = None
    rejected_at: str | None = None
    rejection_reason: str | None = None
    trade_reason: str | None = None
    entry_trigger: str | None = None
    suggested_limit_price: float | None = None
    profit_target_pct: float | None = None
    stop_loss_pct: float | None = None
    time_stop_rule: str | None = None
    technical_invalidation_rule: str | None = None
    max_dollar_risk: float | None = None
    risk_notes: str | None = None
    review_notes: str | None = None
    override_reason: str | None = None
    plan_complete: int = 0
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
        _ensure_column(conn, "signal_snapshot", "signal_date", "TEXT")
        _ensure_column(conn, "signal_snapshot", "candidate_key", "TEXT")
        _ensure_column(conn, "signal_snapshot", "lifecycle_state", "TEXT")
        _ensure_column(conn, "signal_snapshot", "high_water_mark", "REAL")
        _ensure_column(conn, "signal_snapshot", "stop_price", "REAL")
        _ensure_column(conn, "signal_snapshot", "stop_reason", "TEXT")
        _ensure_column(conn, "signal_snapshot", "rejected_at", "TEXT")
        _ensure_column(conn, "signal_snapshot", "rejection_reason", "TEXT")
        _ensure_column(conn, "signal_snapshot", "trade_reason", "TEXT")
        _ensure_column(conn, "signal_snapshot", "entry_trigger", "TEXT")
        _ensure_column(conn, "signal_snapshot", "suggested_limit_price", "REAL")
        _ensure_column(conn, "signal_snapshot", "profit_target_pct", "REAL")
        _ensure_column(conn, "signal_snapshot", "stop_loss_pct", "REAL")
        _ensure_column(conn, "signal_snapshot", "time_stop_rule", "TEXT")
        _ensure_column(conn, "signal_snapshot", "technical_invalidation_rule", "TEXT")
        _ensure_column(conn, "signal_snapshot", "max_dollar_risk", "REAL")
        _ensure_column(conn, "signal_snapshot", "risk_notes", "TEXT")
        _ensure_column(conn, "signal_snapshot", "review_notes", "TEXT")
        _ensure_column(conn, "signal_snapshot", "override_reason", "TEXT")
        _ensure_column(conn, "signal_snapshot", "plan_complete", "INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshot_timestamp ON signal_snapshot(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshot_ticker ON signal_snapshot(ticker)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshot_sector ON signal_snapshot(sector)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshot_candidate_key ON signal_snapshot(candidate_key)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_snapshot_hash ON signal_snapshot(signal_hash)")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_snapshot_open_idea
            ON signal_snapshot(ticker, option_symbol)
            WHERE status = 'OPEN'
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_id INTEGER NOT NULL UNIQUE,
                ticker TEXT NOT NULL,
                option_symbol TEXT NOT NULL,
                expiry TEXT NOT NULL,
                strike REAL NOT NULL,
                right TEXT NOT NULL,
                status TEXT NOT NULL,
                lifecycle_state TEXT,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                entry_price REAL NOT NULL,
                current_price REAL,
                close_price REAL,
                close_reason TEXT,
                pnl REAL,
                pnl_pct REAL,
                underlying_entry_price REAL,
                underlying_current_price REAL,
                underlying_return_pct REAL,
                high_water_mark REAL,
                stop_price REAL,
                stop_reason TEXT,
                review_notes TEXT,
                override_reason TEXT,
                latest_notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trade_marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_trade_id INTEGER NOT NULL,
                recommendation_id INTEGER NOT NULL,
                marked_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                option_symbol TEXT NOT NULL,
                bid REAL,
                ask REAL,
                mid REAL,
                current_price REAL,
                underlying_current_price REAL,
                pnl REAL,
                pnl_pct REAL,
                lifecycle_state TEXT,
                stop_price REAL,
                exit_signal TEXT NOT NULL,
                signal_reason TEXT,
                notes TEXT,
                UNIQUE(paper_trade_id, marked_at)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_trades_recommendation ON paper_trades(recommendation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_trade_marks_trade ON paper_trade_marks(paper_trade_id, marked_at)")
        _backfill_candidate_metadata(conn)
        _supersede_non_primary_review_candidates(conn)


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
        before = conn.total_changes
        for record in records:
            _upsert_recommendation_record(conn, record)
        logged = conn.total_changes - before
        _supersede_non_primary_review_candidates(conn)
        return logged


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
        signal_date = _signal_date(timestamp)
        candidate_key = _candidate_key(option.ticker, option.expiry, float(option.strike), _right_name(option), signal_date)
        notes = _recommendation_notes(option, stock, sector, risk)
        plan = _trade_plan_fields(option, stock, sector, risk, config, notes)
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
            notes=notes,
            bid=option.bid,
            ask=option.ask,
            mid=option.mid,
            entry_price=option.ask if status == OPEN else None,
            current_price=option.ask if status == OPEN else None,
            status=status,
            opened_at=timestamp if status == OPEN else None,
            underlying_entry_price=stock.last_price if stock and status == OPEN else None,
            underlying_current_price=stock.last_price if stock else None,
            latest_notes=notes,
            signal_date=signal_date,
            candidate_key=candidate_key,
            lifecycle_state=OPEN_INITIAL_RISK if status == OPEN else None,
            high_water_mark=option.ask if status == OPEN else None,
            **plan,
        )
        records.append(RecommendationRecord(**{**record.__dict__, "signal_hash": _signal_hash(record)}))
    return records


def list_recommendations(db_path: str = DEFAULT_DB_PATH, limit: int = 100, ticker: str | None = None) -> list[dict[str, Any]]:
    initialize_recommendation_db(db_path)
    limit = max(1, min(int(limit), 1000))
    params: list[Any] = [SUPERSEDED]
    where = "WHERE status != ?"
    if ticker:
        where += " AND upper(ticker) = upper(?)"
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


def list_review_required_recommendations(
    db_path: str = DEFAULT_DB_PATH,
    *,
    config: dict | None = None,
) -> list[dict[str, Any]]:
    initialize_recommendation_db(db_path)
    exclude_open_tickers = not _pyramiding_enabled(config)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    *,
                    (
                        SELECT COUNT(*)
                        FROM signal_snapshot alternate
                        WHERE upper(alternate.ticker) = upper(signal_snapshot.ticker)
                          AND alternate.status IN (?, ?)
                    ) AS alternate_contract_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY upper(ticker)
                        ORDER BY
                            recommendation_score DESC,
                            CASE
                                WHEN bid IS NOT NULL AND ask IS NOT NULL AND ask > 0
                                THEN (ask - bid) / ask
                                ELSE 999.0
                            END ASC,
                            COALESCE(oi, 0) DESC,
                            timestamp DESC,
                            id DESC
                    ) AS ticker_rank
                FROM signal_snapshot
                WHERE status = ?
                  AND (
                      ? = 0
                      OR NOT EXISTS (
                          SELECT 1
                          FROM signal_snapshot open_trade
                          WHERE open_trade.status = ?
                            AND upper(open_trade.ticker) = upper(signal_snapshot.ticker)
                      )
                  )
            )
            SELECT *
            FROM ranked
            WHERE ticker_rank = 1
            ORDER BY recommendation_score DESC, timestamp DESC, id DESC
            """,
            (REVIEW_REQUIRED, SUPERSEDED, REVIEW_REQUIRED, 1 if exclude_open_tickers else 0, OPEN),
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


def list_paper_trades(db_path: str = DEFAULT_DB_PATH, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    initialize_recommendation_db(db_path)
    limit = max(1, min(int(limit), 1000))
    params: list[Any] = []
    where = ""
    if status:
        where = "WHERE paper_trades.status = ?"
        params.append(status)
    params.append(limit)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                paper_trades.*,
                signal_snapshot.recommendation_score,
                signal_snapshot.notes AS recommendation_notes,
                signal_snapshot.trade_reason,
                signal_snapshot.profit_target_pct,
                signal_snapshot.stop_loss_pct
            FROM paper_trades
            LEFT JOIN signal_snapshot ON signal_snapshot.id = paper_trades.recommendation_id
            {where}
            ORDER BY paper_trades.opened_at DESC, paper_trades.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def list_open_paper_trades(db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    return list_paper_trades(db_path, status=OPEN, limit=1000)


def list_paper_trade_marks(db_path: str = DEFAULT_DB_PATH, paper_trade_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    initialize_recommendation_db(db_path)
    limit = max(1, min(int(limit), 1000))
    params: list[Any] = []
    where = ""
    if paper_trade_id is not None:
        where = "WHERE paper_trade_id = ?"
        params.append(paper_trade_id)
    params.append(limit)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT *
            FROM paper_trade_marks
            {where}
            ORDER BY marked_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def record_paper_trade_mark(
    db_path: str,
    recommendation_id: int,
    *,
    marked_at: str,
    bid: float | None,
    ask: float | None,
    mid: float | None,
    current_price: float | None,
    underlying_current_price: float | None,
    lifecycle_state: str | None,
    stop_price: float | None,
    exit_signal: str,
    signal_reason: str | None = None,
    notes: str | None = None,
) -> None:
    recommendation = get_recommendation(db_path, recommendation_id)
    if recommendation is None:
        return
    trade = _get_paper_trade_by_recommendation(db_path, recommendation_id)
    if trade is None:
        return
    pnl, pnl_pct = _pnl(recommendation.get("entry_price"), current_price)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            INSERT INTO paper_trade_marks (
                paper_trade_id,
                recommendation_id,
                marked_at,
                ticker,
                option_symbol,
                bid,
                ask,
                mid,
                current_price,
                underlying_current_price,
                pnl,
                pnl_pct,
                lifecycle_state,
                stop_price,
                exit_signal,
                signal_reason,
                notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_trade_id, marked_at) DO UPDATE SET
                bid = excluded.bid,
                ask = excluded.ask,
                mid = excluded.mid,
                current_price = excluded.current_price,
                underlying_current_price = excluded.underlying_current_price,
                pnl = excluded.pnl,
                pnl_pct = excluded.pnl_pct,
                lifecycle_state = excluded.lifecycle_state,
                stop_price = excluded.stop_price,
                exit_signal = excluded.exit_signal,
                signal_reason = excluded.signal_reason,
                notes = excluded.notes
            """,
            (
                trade["id"],
                recommendation_id,
                marked_at,
                recommendation["ticker"],
                recommendation["option_symbol"],
                bid,
                ask,
                mid,
                current_price,
                underlying_current_price,
                pnl,
                pnl_pct,
                lifecycle_state,
                stop_price,
                exit_signal,
                signal_reason,
                notes,
            ),
        )


def _get_paper_trade_by_recommendation(db_path: str, recommendation_id: int) -> dict[str, Any] | None:
    initialize_recommendation_db(db_path)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM paper_trades WHERE recommendation_id = ?",
            (recommendation_id,),
        ).fetchone()
    return dict(row) if row else None


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
    lifecycle_state: str | None = None,
    high_water_mark: float | None = None,
    stop_price: float | None = None,
    stop_reason: str | None = None,
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
                lifecycle_state = COALESCE(?, lifecycle_state),
                high_water_mark = COALESCE(?, high_water_mark),
                stop_price = COALESCE(?, stop_price),
                stop_reason = COALESCE(?, stop_reason),
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
                lifecycle_state,
                high_water_mark,
                stop_price,
                stop_reason,
                latest_notes,
                recommendation_id,
            ),
        )
    updated = get_recommendation(db_path, recommendation_id)
    if updated is not None:
        update_paper_trade_quote_from_recommendation(db_path, updated)


def update_paper_trade_quote_from_recommendation(db_path: str, recommendation: dict[str, Any]) -> None:
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            UPDATE paper_trades
            SET current_price = ?,
                underlying_current_price = ?,
                underlying_return_pct = ?,
                pnl = ?,
                pnl_pct = ?,
                lifecycle_state = ?,
                high_water_mark = ?,
                stop_price = ?,
                stop_reason = ?,
                latest_notes = ?
            WHERE recommendation_id = ?
              AND status = ?
            """,
            (
                recommendation.get("current_price"),
                recommendation.get("underlying_current_price"),
                recommendation.get("underlying_return_pct"),
                recommendation.get("pnl"),
                recommendation.get("pnl_pct"),
                recommendation.get("lifecycle_state"),
                recommendation.get("high_water_mark"),
                recommendation.get("stop_price"),
                recommendation.get("stop_reason"),
                recommendation.get("latest_notes"),
                recommendation.get("id"),
                OPEN,
            ),
        )


def approve_recommendation(
    db_path: str,
    recommendation_id: int,
    *,
    approved_at: str | None = None,
    entry_price: float | None = None,
    latest_notes: str | None = None,
    config: dict | None = None,
    review_notes: str | None = None,
    override_reason: str | None = None,
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
    if not _pyramiding_enabled(config) and _active_open_ticker_exists(db_path, existing["ticker"]):
        raise ValueError("An OPEN recommendation already exists for this ticker")
    clean_review_notes = (review_notes or "").strip()
    if not clean_review_notes:
        raise ValueError("Approval requires review notes")
    clean_override_reason = (override_reason or "").strip()
    if not _plan_is_complete(existing) and not clean_override_reason:
        raise ValueError("Incomplete trade plan requires an override reason")

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
                lifecycle_state = ?,
                high_water_mark = ?,
                stop_price = ?,
                stop_reason = ?,
                review_notes = ?,
                override_reason = ?,
                latest_notes = COALESCE(?, latest_notes)
            WHERE id = ? AND status = ?
            """,
            (
                OPEN,
                approved_at,
                float(approved_entry),
                float(approved_entry),
                OPEN_INITIAL_RISK,
                float(approved_entry),
                _initial_stop_price(float(approved_entry), config),
                "initial_premium_risk",
                clean_review_notes,
                clean_override_reason or None,
                latest_notes,
                recommendation_id,
                REVIEW_REQUIRED,
            ),
        )
    approved = get_recommendation(db_path, recommendation_id)
    if approved is None:
        raise ValueError("Approved recommendation could not be loaded")
    _create_paper_trade_from_recommendation(db_path, approved)
    return approved


def _create_paper_trade_from_recommendation(db_path: str, recommendation: dict[str, Any]) -> None:
    current_price = recommendation.get("current_price")
    pnl, pnl_pct = _pnl(recommendation.get("entry_price"), current_price)
    stop_price = recommendation.get("stop_price")
    if stop_price is None and recommendation.get("entry_price") is not None:
        stop_loss_pct = recommendation.get("stop_loss_pct")
        stop_price = max(0.0, float(recommendation["entry_price"]) * (1.0 + float(stop_loss_pct if stop_loss_pct is not None else -0.25)))
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            INSERT INTO paper_trades (
                recommendation_id,
                ticker,
                option_symbol,
                expiry,
                strike,
                right,
                status,
                lifecycle_state,
                opened_at,
                entry_price,
                current_price,
                close_price,
                close_reason,
                pnl,
                pnl_pct,
                underlying_entry_price,
                underlying_current_price,
                underlying_return_pct,
                high_water_mark,
                stop_price,
                stop_reason,
                review_notes,
                override_reason,
                latest_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(recommendation_id) DO UPDATE SET
                status = excluded.status,
                lifecycle_state = excluded.lifecycle_state,
                opened_at = excluded.opened_at,
                entry_price = excluded.entry_price,
                current_price = excluded.current_price,
                close_price = excluded.close_price,
                close_reason = excluded.close_reason,
                pnl = excluded.pnl,
                pnl_pct = excluded.pnl_pct,
                underlying_entry_price = excluded.underlying_entry_price,
                underlying_current_price = excluded.underlying_current_price,
                underlying_return_pct = excluded.underlying_return_pct,
                high_water_mark = excluded.high_water_mark,
                stop_price = excluded.stop_price,
                stop_reason = excluded.stop_reason,
                review_notes = excluded.review_notes,
                override_reason = excluded.override_reason,
                latest_notes = excluded.latest_notes
            """,
            (
                recommendation["id"],
                recommendation["ticker"],
                recommendation["option_symbol"],
                recommendation["expiry"],
                recommendation["strike"],
                recommendation["right"],
                recommendation["status"],
                recommendation.get("lifecycle_state"),
                recommendation["opened_at"],
                recommendation["entry_price"],
                current_price,
                recommendation.get("close_price"),
                recommendation.get("close_reason"),
                pnl,
                pnl_pct,
                recommendation.get("underlying_entry_price"),
                recommendation.get("underlying_current_price"),
                recommendation.get("underlying_return_pct"),
                recommendation.get("high_water_mark"),
                stop_price,
                recommendation.get("stop_reason") or ("initial_premium_risk" if stop_price is not None else None),
                recommendation.get("review_notes"),
                recommendation.get("override_reason"),
                recommendation.get("latest_notes"),
            ),
        )


def reject_recommendation(
    db_path: str,
    recommendation_id: int,
    *,
    rejected_at: str | None = None,
    rejection_reason: str | None = None,
    latest_notes: str | None = None,
) -> dict[str, Any]:
    initialize_recommendation_db(db_path)
    rejected_at = rejected_at or datetime.now().astimezone().isoformat(timespec="seconds")
    existing = get_recommendation(db_path, recommendation_id)
    if existing is None:
        raise ValueError("Recommendation not found")
    if existing.get("status") != REVIEW_REQUIRED:
        raise ValueError("Only REVIEW_REQUIRED recommendations can be rejected")

    reason = (rejection_reason or "manual_reject").strip() or "manual_reject"
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            UPDATE signal_snapshot
            SET status = ?,
                rejected_at = ?,
                rejection_reason = ?,
                latest_notes = COALESCE(?, latest_notes)
            WHERE id = ? AND status = ?
            """,
            (
                REJECTED,
                rejected_at,
                reason,
                latest_notes or f"Rejected during manual review: {reason}",
                recommendation_id,
                REVIEW_REQUIRED,
            ),
        )
    rejected = get_recommendation(db_path, recommendation_id)
    if rejected is None:
        raise ValueError("Rejected recommendation could not be loaded")
    return rejected


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
                lifecycle_state = ?,
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
                EXITED,
                latest_notes,
                recommendation_id,
            ),
        )
    closed = get_recommendation(db_path, recommendation_id)
    if closed is not None:
        close_paper_trade_from_recommendation(db_path, closed)


def close_paper_trade_from_recommendation(db_path: str, recommendation: dict[str, Any]) -> None:
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            UPDATE paper_trades
            SET status = ?,
                lifecycle_state = ?,
                closed_at = ?,
                close_price = ?,
                current_price = ?,
                close_reason = ?,
                pnl = ?,
                pnl_pct = ?,
                latest_notes = ?
            WHERE recommendation_id = ?
            """,
            (
                recommendation.get("status"),
                recommendation.get("lifecycle_state"),
                recommendation.get("closed_at"),
                recommendation.get("close_price"),
                recommendation.get("current_price"),
                recommendation.get("close_reason"),
                recommendation.get("pnl"),
                recommendation.get("pnl_pct"),
                recommendation.get("latest_notes"),
                recommendation.get("id"),
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


def backfill_trade_plan_context(db_path: str = DEFAULT_DB_PATH, config: dict | None = None) -> int:
    initialize_recommendation_db(db_path)
    cfg = config or {}
    exit_config = cfg.get("exit", {})
    timeframe_5m = cfg.get("timeframe_5m", {})
    entry_config = cfg.get("entry", {})
    profit_target_pct = float(exit_config.get("profit_target_pct", 0.40))
    stop_loss_pct = float(exit_config.get("stop_loss_pct", -0.25))
    max_holding_days = int(exit_config.get("max_holding_days", 5))
    entry_trigger = str(timeframe_5m.get("entry_trigger") or entry_config.get("entry_trigger") or "manual_review_confirmed")
    technical_rule = _technical_invalidation_rule(exit_config)
    time_stop_rule = f"Exit after {max_holding_days} holding days"

    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM signal_snapshot
            WHERE trade_reason IS NULL
               OR entry_trigger IS NULL
               OR suggested_limit_price IS NULL
               OR profit_target_pct IS NULL
               OR stop_loss_pct IS NULL
               OR time_stop_rule IS NULL
               OR technical_invalidation_rule IS NULL
               OR max_dollar_risk IS NULL
               OR risk_notes IS NULL
               OR plan_complete = 0
            """
        ).fetchall()
        before = conn.total_changes
        for row in rows:
            suggested_limit = _first_positive(row["ask"], row["mid"], row["bid"], row["entry_price"])
            risk_notes = row["risk_notes"] or row["notes"] or "Risk checks require manual validation."
            fields = {
                "trade_reason": row["trade_reason"] or row["notes"],
                "entry_trigger": row["entry_trigger"] or entry_trigger,
                "suggested_limit_price": row["suggested_limit_price"] or suggested_limit,
                "profit_target_pct": row["profit_target_pct"] if row["profit_target_pct"] is not None else profit_target_pct,
                "stop_loss_pct": row["stop_loss_pct"] if row["stop_loss_pct"] is not None else stop_loss_pct,
                "time_stop_rule": row["time_stop_rule"] or time_stop_rule,
                "technical_invalidation_rule": row["technical_invalidation_rule"] or technical_rule,
                "max_dollar_risk": row["max_dollar_risk"] or (suggested_limit * 100 if suggested_limit is not None else None),
                "risk_notes": risk_notes,
            }
            fields["plan_complete"] = 1 if _plan_is_complete(fields) else 0
            conn.execute(
                """
                UPDATE signal_snapshot
                SET trade_reason = ?,
                    entry_trigger = ?,
                    suggested_limit_price = ?,
                    profit_target_pct = ?,
                    stop_loss_pct = ?,
                    time_stop_rule = ?,
                    technical_invalidation_rule = ?,
                    max_dollar_risk = ?,
                    risk_notes = ?,
                    plan_complete = ?
                WHERE id = ?
                """,
                (
                    fields["trade_reason"],
                    fields["entry_trigger"],
                    fields["suggested_limit_price"],
                    fields["profit_target_pct"],
                    fields["stop_loss_pct"],
                    fields["time_stop_rule"],
                    fields["technical_invalidation_rule"],
                    fields["max_dollar_risk"],
                    fields["risk_notes"],
                    fields["plan_complete"],
                    row["id"],
                ),
            )
    return conn.total_changes - before


def backfill_paper_trades(db_path: str = DEFAULT_DB_PATH) -> int:
    initialize_recommendation_db(db_path)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM signal_snapshot
            WHERE status IN ('OPEN', 'CLOSED', 'EXPIRED')
              AND entry_price IS NOT NULL
              AND opened_at IS NOT NULL
            """
        ).fetchall()
    before = len(list_paper_trades(db_path, limit=1000))
    for row in rows:
        _create_paper_trade_from_recommendation(db_path, dict(row))
        if row["status"] in {"CLOSED", "EXPIRED"}:
            close_paper_trade_from_recommendation(db_path, dict(row))
    after = len(list_paper_trades(db_path, limit=1000))
    return after - before


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
        record.signal_date,
        record.candidate_key,
        record.lifecycle_state,
        record.high_water_mark,
        record.stop_price,
        record.stop_reason,
        record.rejected_at,
        record.rejection_reason,
        record.trade_reason,
        record.entry_trigger,
        record.suggested_limit_price,
        record.profit_target_pct,
        record.stop_loss_pct,
        record.time_stop_rule,
        record.technical_invalidation_rule,
        record.max_dollar_risk,
        record.risk_notes,
        record.review_notes,
        record.override_reason,
        record.plan_complete,
        record.signal_hash,
    )


def _upsert_recommendation_record(conn: sqlite3.Connection, record: RecommendationRecord) -> None:
    existing = None
    if record.candidate_key:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            """
            SELECT *
            FROM signal_snapshot
            WHERE candidate_key = ?
              AND status IN (?, ?)
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (record.candidate_key, REVIEW_REQUIRED, WATCH),
        ).fetchone()
        conn.row_factory = None
    if existing is not None:
        existing_dict = dict(existing)
        if _record_matches_existing(record, existing_dict):
            return
        conn.execute(
            """
            UPDATE signal_snapshot
            SET timestamp = ?,
                sector = ?,
                sector_rank = ?,
                stock_rank = ?,
                option_symbol = ?,
                expiry = ?,
                strike = ?,
                right = ?,
                delta = ?,
                gamma = ?,
                theta = ?,
                vega = ?,
                iv = ?,
                oi = ?,
                dte = ?,
                recommendation_score = ?,
                market_regime = ?,
                recommendation_type = ?,
                notes = ?,
                bid = ?,
                ask = ?,
                mid = ?,
                current_price = ?,
                status = ?,
                underlying_current_price = ?,
                latest_notes = ?,
                signal_date = ?,
                trade_reason = ?,
                entry_trigger = ?,
                suggested_limit_price = ?,
                profit_target_pct = ?,
                stop_loss_pct = ?,
                time_stop_rule = ?,
                technical_invalidation_rule = ?,
                max_dollar_risk = ?,
                risk_notes = ?,
                plan_complete = ?,
                signal_hash = ?
            WHERE id = ?
            """,
            (
                record.timestamp,
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
                record.current_price,
                record.status,
                record.underlying_current_price,
                record.latest_notes,
                record.signal_date,
                record.trade_reason,
                record.entry_trigger,
                record.suggested_limit_price,
                record.profit_target_pct,
                record.stop_loss_pct,
                record.time_stop_rule,
                record.technical_invalidation_rule,
                record.max_dollar_risk,
                record.risk_notes,
                record.plan_complete,
                record.signal_hash,
                existing_dict["id"],
            ),
        )
        return

    values = _record_values(record)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        f"""
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
            signal_date,
            candidate_key,
            lifecycle_state,
            high_water_mark,
            stop_price,
            stop_reason,
            rejected_at,
            rejection_reason,
            trade_reason,
            entry_trigger,
            suggested_limit_price,
            profit_target_pct,
            stop_loss_pct,
            time_stop_rule,
            technical_invalidation_rule,
            max_dollar_risk,
            risk_notes,
            review_notes,
            override_reason,
            plan_complete,
            signal_hash
        ) VALUES ({placeholders})
        ON CONFLICT(signal_hash) DO NOTHING
        """,
        values,
    )


def _record_matches_existing(record: RecommendationRecord, existing: dict[str, Any]) -> bool:
    keys = (
        "timestamp",
        "sector",
        "sector_rank",
        "stock_rank",
        "option_symbol",
        "expiry",
        "strike",
        "right",
        "delta",
        "gamma",
        "theta",
        "vega",
        "iv",
        "oi",
        "dte",
        "recommendation_score",
        "market_regime",
        "recommendation_type",
        "notes",
        "bid",
        "ask",
        "mid",
        "status",
        "underlying_current_price",
        "latest_notes",
        "signal_date",
        "trade_reason",
        "entry_trigger",
        "suggested_limit_price",
        "profit_target_pct",
        "stop_loss_pct",
        "time_stop_rule",
        "technical_invalidation_rule",
        "max_dollar_risk",
        "risk_notes",
        "plan_complete",
        "signal_hash",
    )
    values = record.__dict__
    return all(_equivalent(values.get(key), existing.get(key)) for key in keys)


def _equivalent(left: Any, right: Any) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        if left is None or right is None:
            return left is None and right is None
        return abs(float(left) - float(right)) < 0.00000001
    return left == right


def _backfill_candidate_metadata(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, ticker, expiry, strike, right, timestamp
        FROM signal_snapshot
        WHERE candidate_key IS NULL
           OR candidate_key = ''
           OR signal_date IS NULL
           OR signal_date = ''
        """
    ).fetchall()
    conn.row_factory = None
    for row in rows:
        signal_date = _signal_date(str(row["timestamp"]))
        candidate_key = _candidate_key(
            str(row["ticker"]),
            str(row["expiry"]),
            float(row["strike"]),
            str(row["right"]),
            signal_date,
        )
        conn.execute(
            """
            UPDATE signal_snapshot
            SET signal_date = ?,
                candidate_key = ?
            WHERE id = ?
            """,
            (signal_date, candidate_key, row["id"]),
        )


def _supersede_non_primary_review_candidates(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    rows = [dict(row) for row in conn.execute("SELECT * FROM signal_snapshot WHERE status = ?", (REVIEW_REQUIRED,)).fetchall()]
    open_tickers = {
        str(row[0]).upper()
        for row in conn.execute("SELECT DISTINCT ticker FROM signal_snapshot WHERE status = ?", (OPEN,)).fetchall()
    }
    conn.row_factory = None
    if not rows:
        return

    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_ticker.setdefault(str(row["ticker"]).upper(), []).append(row)

    keep_ids: set[int] = set()
    superseded_ids: list[int] = []
    for ticker, ticker_rows in by_ticker.items():
        if ticker in open_tickers:
            superseded_ids.extend(int(row["id"]) for row in ticker_rows)
            continue
        ranked = sorted(ticker_rows, key=_review_rank_key)
        keep_ids.add(int(ranked[0]["id"]))
        superseded_ids.extend(int(row["id"]) for row in ranked[1:])

    if not superseded_ids:
        return

    conn.executemany(
        """
        UPDATE signal_snapshot
        SET status = ?,
            latest_notes = CASE
                WHEN latest_notes IS NULL OR latest_notes = ''
                THEN 'Superseded by current best review candidate.'
                ELSE latest_notes || ' Superseded by current best review candidate.'
            END
        WHERE id = ?
          AND status = ?
        """,
        [(SUPERSEDED, row_id, REVIEW_REQUIRED) for row_id in superseded_ids if row_id not in keep_ids],
    )


def _review_rank_key(row: dict[str, Any]) -> tuple:
    spread = 999.0
    bid = row.get("bid")
    ask = row.get("ask")
    if bid is not None and ask is not None and float(ask) > 0:
        spread = (float(ask) - float(bid)) / float(ask)
    parsed_timestamp = _parse_datetime(str(row.get("timestamp") or ""))
    timestamp_rank = -(parsed_timestamp.timestamp() if parsed_timestamp else 0.0)
    return (
        -float(row.get("recommendation_score") or 0.0),
        spread,
        -int(row.get("oi") or 0),
        timestamp_rank,
        -int(row.get("id") or 0),
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


def _active_open_ticker_exists(db_path: str, ticker: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        row = conn.execute(
            """
            SELECT 1
            FROM signal_snapshot
            WHERE upper(ticker) = upper(?)
              AND status = ?
            LIMIT 1
            """,
            (ticker, OPEN),
        ).fetchone()
    return row is not None


def _pyramiding_enabled(config: dict | None) -> bool:
    risk_controls = (config or {}).get("risk_controls", {})
    paper = (config or {}).get("paper_trading", {})
    if "pyramiding_enabled" in paper:
        return bool(paper["pyramiding_enabled"])
    if "allow_pyramiding" in paper:
        return bool(paper["allow_pyramiding"])
    return int(risk_controls.get("max_open_positions_per_ticker", 1) or 1) > 1


def _initial_stop_price(entry_price: float, config: dict | None) -> float:
    stop_loss_pct = float((config or {}).get("exit", {}).get("stop_loss_pct", -0.25))
    return max(0.0, entry_price * (1.0 + stop_loss_pct))


def _plan_is_complete(row: dict[str, Any]) -> bool:
    required_text = (
        "trade_reason",
        "entry_trigger",
        "time_stop_rule",
        "technical_invalidation_rule",
        "risk_notes",
    )
    if any(not str(row.get(key) or "").strip() for key in required_text):
        return False
    required_positive = (
        "suggested_limit_price",
        "profit_target_pct",
        "max_dollar_risk",
    )
    if any(row.get(key) is None or float(row.get(key) or 0) <= 0 for key in required_positive):
        return False
    return row.get("stop_loss_pct") is not None and float(row.get("stop_loss_pct") or 0) < 0


def _auto_open_paper_trades(config: dict | None) -> bool:
    paper = (config or {}).get("paper_trading", {})
    return bool(paper.get("auto_open_paper_trades", paper.get("AUTO_OPEN_PAPER_TRADES", False)))


def _require_manual_approval(config: dict | None) -> bool:
    paper = (config or {}).get("paper_trading", {})
    return bool(paper.get("require_manual_approval", paper.get("REQUIRE_MANUAL_APPROVAL", True)))


def _trade_plan_fields(
    option: OptionSignal,
    stock,
    sector,
    risk,
    config: dict | None,
    notes: str,
) -> dict[str, Any]:
    cfg = config or {}
    exit_config = cfg.get("exit", {})
    timeframe_5m = cfg.get("timeframe_5m", {})
    entry_config = cfg.get("entry", {})
    suggested_limit = _suggested_limit_price(option)
    profit_target_pct = float(exit_config.get("profit_target_pct", 0.40))
    stop_loss_pct = float(exit_config.get("stop_loss_pct", -0.25))
    max_holding_days = int(exit_config.get("max_holding_days", 5))
    entry_trigger = str(timeframe_5m.get("entry_trigger") or entry_config.get("entry_trigger") or "manual_review_confirmed")
    technical_rule = _technical_invalidation_rule(exit_config)
    risk_notes = risk.notes if risk and risk.notes else "Risk checks passed; validate sizing and liquidity before approval."
    max_dollar_risk = suggested_limit * 100 if suggested_limit is not None else None
    fields = {
        "trade_reason": notes,
        "entry_trigger": entry_trigger,
        "suggested_limit_price": suggested_limit,
        "profit_target_pct": profit_target_pct,
        "stop_loss_pct": stop_loss_pct,
        "time_stop_rule": f"Exit after {max_holding_days} holding days",
        "technical_invalidation_rule": technical_rule,
        "max_dollar_risk": max_dollar_risk,
        "risk_notes": risk_notes,
    }
    fields["plan_complete"] = 1 if _plan_is_complete(fields) else 0
    return fields


def _suggested_limit_price(option: OptionSignal) -> float | None:
    for value in (option.ask, option.mid, option.bid):
        if value is not None and float(value) > 0:
            return float(value)
    return None


def _first_positive(*values) -> float | None:
    for value in values:
        if value is not None and float(value) > 0:
            return float(value)
    return None


def _technical_invalidation_rule(exit_config: dict) -> str:
    rules = []
    if exit_config.get("exit_on_close_below_ema21", True):
        rules.append("close below EMA21")
    if exit_config.get("exit_on_60m_ema21_loss", True):
        rules.append("60m EMA21 loss")
    if exit_config.get("exit_on_5m_vwap_loss", True):
        rules.append("5m VWAP loss")
    if not rules:
        rules.append("manual technical invalidation")
    return "; ".join(rules)


def _signal_date(timestamp: str) -> str:
    parsed = _parse_datetime(timestamp)
    if parsed:
        return parsed.date().isoformat()
    return timestamp[:10]


def _candidate_key(ticker: str, expiry: str, strike: float, right: str, signal_date: str) -> str:
    return "|".join(
        [
            ticker.upper(),
            str(expiry),
            f"{float(strike):.4f}",
            right.upper(),
            signal_date,
        ]
    )


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
