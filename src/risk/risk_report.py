from __future__ import annotations

import pandas as pd

from src.utils import ensure_parent_dir


def save_risk_events(events: list[dict], path: str) -> None:
    ensure_parent_dir(path)
    pd.DataFrame(events).to_csv(path, index=False)
