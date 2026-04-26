from __future__ import annotations

import pandas as pd

from src.models import MomentumSignal


def calculate_momentum(ticker: str, bars: pd.DataFrame, config: dict) -> MomentumSignal | None:
    if bars is None or bars.empty:
        return None
    if "close" not in bars.columns or "volume" not in bars.columns:
        return None

    momentum_config = config.get("momentum", {})
    strategy_config = config.get("strategy", {})
    lookback_days = int(momentum_config.get("lookback_days", 10))
    volume_lookback_days = int(momentum_config.get("volume_lookback_days", 10))
    min_price = float(strategy_config.get("min_price", 0))

    required_bars = max(lookback_days, volume_lookback_days, 10) + 1
    clean_bars = bars.dropna(subset=["close", "volume"]).copy()
    if len(clean_bars) < required_bars:
        return None

    last_price = float(clean_bars["close"].iloc[-1])
    if last_price < min_price:
        return None

    close_5d = float(clean_bars["close"].iloc[-6])
    close_10d = float(clean_bars["close"].iloc[-11])
    if close_5d <= 0 or close_10d <= 0:
        return None

    return_5d = last_price / close_5d - 1
    return_10d = last_price / close_10d - 1

    latest_volume = float(clean_bars["volume"].iloc[-1])
    average_volume_10d = float(clean_bars["volume"].iloc[-volume_lookback_days:].mean())
    if average_volume_10d <= 0:
        return None

    volume_ratio = latest_volume / average_volume_10d
    momentum_score = (return_5d * 0.45) + (return_10d * 0.35) + ((volume_ratio - 1) * 0.20)
    if momentum_score <= 0:
        return None

    return MomentumSignal(
        ticker=ticker,
        last_price=last_price,
        momentum_score=float(momentum_score),
        return_5d=float(return_5d),
        return_10d=float(return_10d),
        volume_ratio=float(volume_ratio),
    )
