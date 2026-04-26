from __future__ import annotations

import numpy as np
import pandas as pd


def estimate_historical_volatility(
    prices: pd.Series,
    lookback_days: int = 20,
    floor: float = 0.20,
    ceiling: float = 1.20,
) -> pd.Series:
    daily_returns = prices.pct_change()
    rolling_std = daily_returns.rolling(lookback_days).std()
    annualized_vol = rolling_std * np.sqrt(252)
    return annualized_vol.clip(lower=floor, upper=ceiling)
