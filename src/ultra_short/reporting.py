from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.ultra_short.repository import (
    CLOSED,
    REJECTED,
    list_ultra_short_candidates,
    list_ultra_short_paper_trades,
    list_ultra_short_trade_marks,
)
from src.utils import ensure_parent_dir


DEFAULT_EXPORT_PATHS = {
    "candidates_csv": "output/ultra_short_candidates.csv",
    "trades_csv": "output/ultra_short_trades.csv",
    "marks_csv": "output/ultra_short_marks.csv",
    "rejected_csv": "output/ultra_short_rejected_setups.csv",
    "analytics_json": "output/ultra_short_analytics.json",
}


def build_ultra_short_analytics(db_path: str) -> dict[str, Any]:
    trades = list_ultra_short_paper_trades(db_path, limit=10000)
    candidates = list_ultra_short_candidates(db_path, limit=10000)
    closed_trades = [trade for trade in trades if trade.get("state") == CLOSED]
    rejected = [candidate for candidate in candidates if candidate.get("status") == REJECTED]
    return {
        "win_loss": _win_loss_analytics(closed_trades),
        "rejections": _rejection_analytics(rejected),
        "activity": _activity_analytics(candidates, trades),
    }


def export_ultra_short_reports(db_path: str, config: dict | None = None) -> dict[str, Any]:
    paths = _export_paths(config or {})
    candidates = list_ultra_short_candidates(db_path, limit=10000)
    trades = list_ultra_short_paper_trades(db_path, limit=10000)
    marks = list_ultra_short_trade_marks(db_path, limit=10000)
    rejected = [candidate for candidate in candidates if candidate.get("status") == REJECTED]
    analytics = build_ultra_short_analytics(db_path)

    _write_csv(paths["candidates_csv"], candidates)
    _write_csv(paths["trades_csv"], trades)
    _write_csv(paths["marks_csv"], marks)
    _write_csv(paths["rejected_csv"], rejected)
    ensure_parent_dir(paths["analytics_json"])
    with Path(paths["analytics_json"]).open("w", encoding="utf-8") as file:
        json.dump(analytics, file, indent=2)

    return {
        "paths": paths,
        "row_counts": {
            "candidates": len(candidates),
            "trades": len(trades),
            "marks": len(marks),
            "rejected": len(rejected),
        },
        "analytics": analytics,
    }


def _win_loss_analytics(closed_trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [_safe_float(trade.get("pnl")) for trade in closed_trades]
    pnls = [pnl for pnl in pnls if pnl is not None]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    breakeven = [pnl for pnl in pnls if pnl == 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    return {
        "closed_trades": len(closed_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "breakeven_trades": len(breakeven),
        "win_rate": (len(wins) / len(closed_trades)) if closed_trades else 0.0,
        "total_pnl": sum(pnls),
        "average_pnl": (sum(pnls) / len(pnls)) if pnls else 0.0,
        "average_win": (sum(wins) / len(wins)) if wins else 0.0,
        "average_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "profit_factor": (gross_profit / abs(gross_loss)) if gross_loss else 0.0,
        "exit_reason_counts": _counts(closed_trades, "exit_reason"),
    }


def _rejection_analytics(rejected: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [_safe_float(candidate.get("ultra_short_score")) for candidate in rejected]
    scores = [score for score in scores if score is not None]
    return {
        "rejected_setups": len(rejected),
        "average_rejected_score": (sum(scores) / len(scores)) if scores else 0.0,
        "by_reason": _counts(rejected, "rejection_reason"),
        "by_direction": _counts(rejected, "direction"),
        "by_setup_state": _counts(rejected, "setup_state"),
    }


def _activity_analytics(candidates: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "candidate_count": len(candidates),
        "candidate_status_counts": _counts(candidates, "status"),
        "candidate_direction_counts": _counts(candidates, "direction"),
        "paper_trade_count": len(trades),
        "paper_trade_state_counts": _counts(trades, "state"),
    }


def _export_paths(config: dict) -> dict[str, str]:
    configured = config.get("ultra_short_exports", {})
    output = config.get("output", {})
    return {
        key: str(configured.get(key) or output.get(f"ultra_short_{key}") or default)
        for key, default in DEFAULT_EXPORT_PATHS.items()
    }


def _write_csv(path: str, rows: list[dict[str, Any]]) -> None:
    ensure_parent_dir(path)
    pd.DataFrame(rows).to_csv(path, index=False)


def _counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "UNKNOWN")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
