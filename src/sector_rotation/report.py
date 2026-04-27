from __future__ import annotations

import pandas as pd

from src.utils import ensure_parent_dir


def save_sector_scores(scores: pd.DataFrame, path: str) -> None:
    ensure_parent_dir(path)
    scores.to_csv(path, index=False)


def save_weekly_universes(universes: pd.DataFrame, path: str) -> None:
    ensure_parent_dir(path)
    universes.to_csv(path, index=False)
