from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_sector_etfs(path: str | Path = "data/sector_etfs.csv") -> pd.DataFrame:
    data = pd.read_csv(path)
    required = {"sector", "etf", "description"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Sector ETF file missing columns: {', '.join(sorted(missing))}")
    return data


def load_sector_map(path: str | Path = "data/sector_map.csv") -> pd.DataFrame:
    data = pd.read_csv(path)
    required = {"ticker", "sector", "sector_etf"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Sector map file missing columns: {', '.join(sorted(missing))}")
    data["ticker"] = data["ticker"].str.upper()
    data["sector_etf"] = data["sector_etf"].str.upper()
    return data
