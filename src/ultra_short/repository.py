from __future__ import annotations

import sqlite3
from datetime import datetime
from hashlib import sha256
from typing import Any

from src.recommendation_logging import recommendation_db_path
from src.utils import ensure_parent_dir


GENERATED = "GENERATED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
APPROVED_FOR_PAPER_TRADE = "APPROVED_FOR_PAPER_TRADE"
OPEN = "OPEN"
EXIT_SIGNAL = "EXIT_SIGNAL"
REJECTED = "REJECTED"
CLOSED = "CLOSED"
OPEN_INITIAL_RISK = "OPEN_INITIAL_RISK"
PROTECTION_MODE = "PROTECTION_MODE"
PROTECTED_BREAKEVEN = "PROTECTED_BREAKEVEN"
TRAILING_PROFIT = "TRAILING_PROFIT"


def ultra_short_db_path(config: dict) -> str:
    return str(config.get("ultra_short", {}).get("database_path") or recommendation_db_path(config))


def initialize_ultra_short_db(db_path: str) -> None:
    ensure_parent_dir(db_path)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ultra_short_signal_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                as_of TEXT NOT NULL,
                status TEXT NOT NULL,
                mode TEXT NOT NULL,
                market_mode TEXT,
                call_readiness REAL,
                put_readiness REAL,
                market_bias_score REAL,
                notes TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(as_of)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ultra_short_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_as_of TEXT NOT NULL,
                candidate_key TEXT NOT NULL UNIQUE,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                setup_state TEXT NOT NULL,
                market_bias_score REAL,
                intraday_sector_score REAL,
                ticker_vwap_setup_score REAL,
                entry_trigger_score REAL,
                option_contract_quality_score REAL,
                swing_quality_score REAL,
                ultra_short_score REAL NOT NULL,
                contract_symbol TEXT,
                expiry TEXT,
                strike REAL,
                right TEXT,
                bid REAL,
                ask REAL,
                suggested_premium REAL,
                delta REAL,
                theta REAL,
                iv REAL,
                open_interest INTEGER,
                dte INTEGER,
                spread_pct REAL,
                entry_trigger TEXT,
                invalidation_rule TEXT,
                stop_rule TEXT,
                time_rule TEXT,
                status TEXT NOT NULL,
                review_notes TEXT,
                rejection_reason TEXT,
                approved_at TEXT,
                rejected_at TEXT,
                override_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ultra_short_paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL UNIQUE,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                contract_symbol TEXT,
                expiry TEXT,
                strike REAL,
                right TEXT,
                state TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                entry_price REAL,
                current_price REAL,
                exit_price REAL,
                pnl REAL,
                pnl_pct REAL,
                stop_state TEXT,
                stop_price REAL,
                vwap_invalidation TEXT,
                exit_signal TEXT,
                exit_reason TEXT,
                review_notes TEXT,
                override_reason TEXT
            )
            """
        )
        _ensure_column(conn, "ultra_short_paper_trades", "high_water_mark", "REAL")
        _ensure_column(conn, "ultra_short_paper_trades", "last_marked_at", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ultra_short_trade_marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_trade_id INTEGER NOT NULL,
                candidate_id INTEGER NOT NULL,
                marked_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                contract_symbol TEXT,
                current_price REAL,
                pnl REAL,
                pnl_pct REAL,
                stop_state TEXT,
                stop_price REAL,
                signal TEXT,
                reason TEXT,
                UNIQUE(paper_trade_id, marked_at)
            )
            """
        )
        _ensure_column(conn, "ultra_short_trade_marks", "stop_state", "TEXT")
        _ensure_column(conn, "ultra_short_trade_marks", "stop_price", "REAL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ultra_short_candidates_status ON ultra_short_candidates(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ultra_short_candidates_ticker ON ultra_short_candidates(ticker)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ultra_short_trades_state ON ultra_short_paper_trades(state)")


def persist_ultra_short_snapshot(snapshot: dict[str, Any], db_path: str) -> int:
    initialize_ultra_short_db(db_path)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    market_bias = snapshot.get("market_bias") or {}
    candidates = list(snapshot.get("call_setups") or []) + list(snapshot.get("put_setups") or [])
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            INSERT INTO ultra_short_signal_snapshot (
                as_of, status, mode, market_mode, call_readiness, put_readiness,
                market_bias_score, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(as_of) DO UPDATE SET
                status = excluded.status,
                mode = excluded.mode,
                market_mode = excluded.market_mode,
                call_readiness = excluded.call_readiness,
                put_readiness = excluded.put_readiness,
                market_bias_score = excluded.market_bias_score,
                notes = excluded.notes
            """,
            (
                snapshot.get("as_of", ""),
                snapshot.get("status", ""),
                snapshot.get("mode", ""),
                market_bias.get("mode"),
                market_bias.get("call_readiness"),
                market_bias.get("put_readiness"),
                market_bias.get("market_bias_score"),
                market_bias.get("notes"),
                now,
            ),
        )
        before = conn.total_changes
        for candidate in candidates:
            _upsert_candidate(conn, snapshot.get("as_of", ""), candidate, now)
        return conn.total_changes - before


def list_ultra_short_candidates(
    db_path: str,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialize_ultra_short_db(db_path)
    where = ""
    params: list[Any] = []
    if status:
        where = "WHERE status = ?"
        params.append(status)
    params.append(limit)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT *
            FROM ultra_short_candidates
            {where}
            ORDER BY ultra_short_score DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def list_review_required_candidates(db_path: str) -> list[dict[str, Any]]:
    return list_ultra_short_candidates(db_path, status=REVIEW_REQUIRED)


def get_ultra_short_candidate(db_path: str, candidate_id: int) -> dict[str, Any] | None:
    initialize_ultra_short_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM ultra_short_candidates WHERE id = ?", (candidate_id,)).fetchone()
    return dict(row) if row else None


def approve_ultra_short_candidate(
    db_path: str,
    candidate_id: int,
    *,
    approved_at: str | None = None,
    entry_price: float | None = None,
    review_notes: str | None = None,
    override_reason: str | None = None,
) -> dict[str, Any]:
    initialize_ultra_short_db(db_path)
    candidate = get_ultra_short_candidate(db_path, candidate_id)
    if candidate is None:
        raise ValueError("Ultra-short candidate not found")
    if candidate.get("status") != REVIEW_REQUIRED:
        raise ValueError("Only REVIEW_REQUIRED ultra-short candidates can be approved")

    clean_review_notes = (review_notes or "").strip()
    if not clean_review_notes:
        raise ValueError("Approval requires review notes")
    clean_override_reason = (override_reason or "").strip()
    if not _plan_is_complete(candidate) and not clean_override_reason:
        raise ValueError("Incomplete ultra-short trade plan requires an override reason")

    approved_at = approved_at or datetime.now().astimezone().isoformat(timespec="seconds")
    approved_entry = entry_price if entry_price is not None else candidate.get("ask") or candidate.get("suggested_premium")
    if approved_entry is not None and float(approved_entry) <= 0:
        raise ValueError("Entry price must be positive when provided")

    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            UPDATE ultra_short_candidates
            SET status = ?,
                approved_at = ?,
                review_notes = ?,
                override_reason = ?,
                updated_at = ?
            WHERE id = ? AND status = ?
            """,
            (
                OPEN,
                approved_at,
                clean_review_notes,
                clean_override_reason or None,
                approved_at,
                candidate_id,
                REVIEW_REQUIRED,
            ),
        )
        conn.execute(
            """
            INSERT INTO ultra_short_paper_trades (
                candidate_id, ticker, direction, contract_symbol, expiry, strike, right,
                state, opened_at, entry_price, current_price, stop_state,
                vwap_invalidation, exit_signal, review_notes, override_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                candidate["ticker"],
                candidate["direction"],
                candidate.get("contract_symbol"),
                candidate.get("expiry"),
                candidate.get("strike"),
                candidate.get("right"),
                OPEN,
                approved_at,
                float(approved_entry) if approved_entry is not None else None,
                float(approved_entry) if approved_entry is not None else None,
                "OPEN_INITIAL_RISK",
                candidate.get("invalidation_rule"),
                "NONE",
                clean_review_notes,
                clean_override_reason or None,
            ),
        )
    approved = get_ultra_short_candidate(db_path, candidate_id)
    return approved or candidate


def reject_ultra_short_candidate(
    db_path: str,
    candidate_id: int,
    *,
    rejected_at: str | None = None,
    rejection_reason: str | None = None,
    review_notes: str | None = None,
) -> dict[str, Any]:
    initialize_ultra_short_db(db_path)
    candidate = get_ultra_short_candidate(db_path, candidate_id)
    if candidate is None:
        raise ValueError("Ultra-short candidate not found")
    if candidate.get("status") not in {GENERATED, REVIEW_REQUIRED}:
        raise ValueError("Only generated or review-required ultra-short candidates can be rejected")
    reason = (rejection_reason or "manual_reject").strip()
    rejected_at = rejected_at or datetime.now().astimezone().isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            UPDATE ultra_short_candidates
            SET status = ?,
                rejected_at = ?,
                rejection_reason = ?,
                review_notes = COALESCE(?, review_notes),
                updated_at = ?
            WHERE id = ?
            """,
            (REJECTED, rejected_at, reason, review_notes, rejected_at, candidate_id),
        )
    rejected = get_ultra_short_candidate(db_path, candidate_id)
    return rejected or candidate


def list_ultra_short_paper_trades(
    db_path: str,
    *,
    state: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialize_ultra_short_db(db_path)
    where = ""
    params: list[Any] = []
    if state:
        where = "WHERE state = ?"
        params.append(state)
    params.append(limit)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT *
            FROM ultra_short_paper_trades
            {where}
            ORDER BY opened_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def list_ultra_short_trade_marks(db_path: str, *, limit: int = 100) -> list[dict[str, Any]]:
    initialize_ultra_short_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM ultra_short_trade_marks
            ORDER BY marked_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_ultra_short_trade_mark(
    db_path: str,
    trade: dict[str, Any],
    *,
    marked_at: str,
    current_price: float | None,
    pnl: float | None,
    pnl_pct: float | None,
    stop_state: str | None,
    stop_price: float | None,
    high_water_mark: float | None,
    exit_signal: str,
    reason: str,
) -> None:
    initialize_ultra_short_db(db_path)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            UPDATE ultra_short_paper_trades
            SET current_price = ?,
                pnl = ?,
                pnl_pct = ?,
                stop_state = COALESCE(?, stop_state),
                stop_price = COALESCE(?, stop_price),
                high_water_mark = COALESCE(?, high_water_mark),
                exit_signal = ?,
                last_marked_at = ?
            WHERE id = ? AND state = ?
            """,
            (
                current_price,
                pnl,
                pnl_pct,
                stop_state,
                stop_price,
                high_water_mark,
                exit_signal,
                marked_at,
                trade["id"],
                OPEN,
            ),
        )
        conn.execute(
            """
            INSERT INTO ultra_short_trade_marks (
                paper_trade_id, candidate_id, marked_at, ticker, contract_symbol,
                current_price, pnl, pnl_pct, stop_state, stop_price, signal, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_trade_id, marked_at) DO UPDATE SET
                current_price = excluded.current_price,
                pnl = excluded.pnl,
                pnl_pct = excluded.pnl_pct,
                stop_state = excluded.stop_state,
                stop_price = excluded.stop_price,
                signal = excluded.signal,
                reason = excluded.reason
            """,
            (
                trade["id"],
                trade["candidate_id"],
                marked_at,
                trade["ticker"],
                trade.get("contract_symbol"),
                current_price,
                pnl,
                pnl_pct,
                stop_state,
                stop_price,
                exit_signal,
                reason,
            ),
        )


def close_ultra_short_trade(
    db_path: str,
    trade: dict[str, Any],
    *,
    closed_at: str,
    exit_price: float | None,
    exit_reason: str,
) -> None:
    initialize_ultra_short_db(db_path)
    pnl, pnl_pct = _pnl(trade.get("entry_price"), exit_price)
    with sqlite3.connect(db_path) as conn:
        _configure_connection(conn)
        conn.execute(
            """
            UPDATE ultra_short_paper_trades
            SET state = ?,
                closed_at = ?,
                exit_price = ?,
                current_price = ?,
                pnl = ?,
                pnl_pct = ?,
                exit_signal = ?,
                exit_reason = ?
            WHERE id = ? AND state = ?
            """,
            (CLOSED, closed_at, exit_price, exit_price, pnl, pnl_pct, "EXIT", exit_reason, trade["id"], OPEN),
        )
        conn.execute(
            """
            UPDATE ultra_short_candidates
            SET status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (CLOSED, closed_at, trade["candidate_id"]),
        )


def get_ultra_short_candidate_for_trade(db_path: str, trade: dict[str, Any]) -> dict[str, Any] | None:
    return get_ultra_short_candidate(db_path, int(trade["candidate_id"]))


def _upsert_candidate(conn: sqlite3.Connection, snapshot_as_of: str, candidate: dict[str, Any], now: str) -> None:
    key = _candidate_key(snapshot_as_of, candidate)
    status = _initial_candidate_status(candidate)
    values = (
        snapshot_as_of,
        key,
        candidate.get("ticker"),
        candidate.get("direction"),
        candidate.get("setup_state"),
        candidate.get("market_bias_score"),
        candidate.get("intraday_sector_score"),
        candidate.get("ticker_vwap_setup_score"),
        candidate.get("entry_trigger_score"),
        candidate.get("option_contract_quality_score"),
        candidate.get("swing_quality_score"),
        candidate.get("ultra_short_score"),
        candidate.get("contract_symbol"),
        candidate.get("expiry"),
        candidate.get("strike"),
        candidate.get("right"),
        candidate.get("bid"),
        candidate.get("ask"),
        candidate.get("suggested_premium"),
        candidate.get("delta"),
        candidate.get("theta"),
        candidate.get("iv"),
        candidate.get("open_interest"),
        candidate.get("dte"),
        candidate.get("spread_pct"),
        candidate.get("entry_trigger"),
        candidate.get("invalidation_rule"),
        candidate.get("stop_rule"),
        candidate.get("time_rule"),
        status,
        candidate.get("review_notes") or None,
        candidate.get("rejection_reason") or None,
        now,
        now,
    )
    conn.execute(
        """
        INSERT INTO ultra_short_candidates (
            snapshot_as_of, candidate_key, ticker, direction, setup_state,
            market_bias_score, intraday_sector_score, ticker_vwap_setup_score,
            entry_trigger_score, option_contract_quality_score, swing_quality_score,
            ultra_short_score, contract_symbol, expiry, strike, right, bid, ask,
            suggested_premium, delta, theta, iv, open_interest, dte, spread_pct,
            entry_trigger, invalidation_rule, stop_rule, time_rule, status,
            review_notes, rejection_reason, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(candidate_key) DO UPDATE SET
            snapshot_as_of = excluded.snapshot_as_of,
            setup_state = excluded.setup_state,
            market_bias_score = excluded.market_bias_score,
            intraday_sector_score = excluded.intraday_sector_score,
            ticker_vwap_setup_score = excluded.ticker_vwap_setup_score,
            entry_trigger_score = excluded.entry_trigger_score,
            option_contract_quality_score = excluded.option_contract_quality_score,
            swing_quality_score = excluded.swing_quality_score,
            ultra_short_score = excluded.ultra_short_score,
            bid = excluded.bid,
            ask = excluded.ask,
            suggested_premium = excluded.suggested_premium,
            delta = excluded.delta,
            theta = excluded.theta,
            iv = excluded.iv,
            open_interest = excluded.open_interest,
            dte = excluded.dte,
            spread_pct = excluded.spread_pct,
            entry_trigger = excluded.entry_trigger,
            invalidation_rule = excluded.invalidation_rule,
            stop_rule = excluded.stop_rule,
            time_rule = excluded.time_rule,
            status = CASE
                WHEN ultra_short_candidates.status IN ('GENERATED', 'REVIEW_REQUIRED')
                THEN excluded.status
                ELSE ultra_short_candidates.status
            END,
            updated_at = excluded.updated_at
        """,
        values,
    )


def _initial_candidate_status(candidate: dict[str, Any]) -> str:
    state = str(candidate.get("setup_state") or "")
    if state.endswith("SETUP_FORMING") or state.endswith("TRIGGERED"):
        return REVIEW_REQUIRED
    if candidate.get("direction") == "PUT" and state == "PUT_WATCH" and candidate.get("contract_symbol"):
        return REVIEW_REQUIRED
    return GENERATED


def _candidate_key(snapshot_as_of: str, candidate: dict[str, Any]) -> str:
    signal_date = str(snapshot_as_of or "")[:10]
    raw = "|".join(
        [
            signal_date,
            str(candidate.get("ticker") or ""),
            str(candidate.get("direction") or ""),
            str(candidate.get("contract_symbol") or ""),
            str(candidate.get("expiry") or ""),
            str(candidate.get("strike") or ""),
            str(candidate.get("setup_state") or ""),
        ]
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def _plan_is_complete(candidate: dict[str, Any]) -> bool:
    required = ["entry_trigger", "invalidation_rule", "stop_rule", "time_rule"]
    return all(str(candidate.get(field) or "").strip() for field in required)


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA synchronous=OFF")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _pnl(entry_price: Any, current_price: Any) -> tuple[float | None, float | None]:
    if entry_price is None or current_price is None:
        return None, None
    entry = float(entry_price)
    current = float(current_price)
    if entry <= 0:
        return None, None
    pnl = current - entry
    return pnl, pnl / entry
