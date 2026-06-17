from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from src.utils import ensure_parent_dir


JOURNAL_COLUMNS = [
    "timestamp",
    "ticker",
    "contract_symbol",
    "signal_score",
    "risk_allowed",
    "platform_validated",
    "chart_validated",
    "trade_taken",
    "contracts",
    "entry_price",
    "manual_notes",
    "outcome_notes",
]


def append_journal_entry(entry: dict, path: str) -> dict:
    ensure_parent_dir(path)
    row = {column: entry.get(column, "") for column in JOURNAL_COLUMNS}
    row["timestamp"] = row["timestamp"] or datetime.now().astimezone().isoformat(timespec="seconds")
    frame = pd.DataFrame([row], columns=JOURNAL_COLUMNS)
    header = not Path(path).exists()
    frame.to_csv(path, mode="a", header=header, index=False)
    return row


def load_journal(path: str) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame(columns=JOURNAL_COLUMNS)
    return pd.read_csv(path)
