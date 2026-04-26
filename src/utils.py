from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd


def load_universe(path: str | Path = "data/universe.csv") -> list[str]:
    universe_path = Path(path)
    if not universe_path.exists():
        raise FileNotFoundError(f"Universe file not found: {universe_path}")

    data = pd.read_csv(universe_path)
    if "ticker" not in data.columns:
        raise ValueError("Universe CSV must contain a 'ticker' column")

    return [
        str(ticker).strip().upper()
        for ticker in data["ticker"].dropna().tolist()
        if str(ticker).strip()
    ]


def parse_ib_expiry(expiry: str) -> date:
    return datetime.strptime(expiry, "%Y%m%d").date()


def calculate_dte(expiry: str, today: date | None = None) -> int:
    today = today or date.today()
    return (parse_ib_expiry(expiry) - today).days


def ensure_parent_dir(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
