from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date

import pandas as pd

from src.utils import ensure_parent_dir


def save_trades_csv(trades, path: str) -> None:
    ensure_parent_dir(path)
    pd.DataFrame([asdict(trade) for trade in trades]).to_csv(path, index=False)


def save_equity_curve_csv(equity_curve, path: str) -> None:
    ensure_parent_dir(path)
    pd.DataFrame(equity_curve).to_csv(path, index=False)


def save_summary_json(summary: dict, path: str) -> None:
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, default=_json_default)


def _json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
