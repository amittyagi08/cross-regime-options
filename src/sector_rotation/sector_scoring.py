from __future__ import annotations

import pandas as pd


def calculate_return(close_series: pd.Series, lookback_days: int) -> float:
    clean = close_series.dropna()
    if len(clean) <= lookback_days:
        return 0.0
    start = float(clean.iloc[-lookback_days - 1])
    end = float(clean.iloc[-1])
    return end / start - 1 if start > 0 else 0.0


def rank_normalize(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    series = pd.Series(values, dtype="float64")
    if len(series) == 1:
        return {series.index[0]: 100.0}
    ranks = series.rank(method="min", pct=True)
    return {key: float(value * 100) for key, value in ranks.items()}


def calculate_sector_scores(
    sector_price_data: dict[str, pd.DataFrame],
    benchmark_data: pd.DataFrame,
    as_of_date,
    config: dict,
) -> pd.DataFrame:
    as_of_date = pd.Timestamp(as_of_date).date()
    benchmark = _as_of(benchmark_data, as_of_date)
    spy_1m = calculate_return(benchmark["close"], 21)
    spy_3m = calculate_return(benchmark["close"], 63)
    rows = []
    components = {"momentum": {}, "relative_strength": {}, "trend": {}, "acceleration": {}}

    for sector, frame in sector_price_data.items():
        data = _as_of(frame, as_of_date)
        if len(data) < 64:
            continue
        close = data["close"]
        return_1w = calculate_return(close, 5)
        return_1m = calculate_return(close, 21)
        return_3m = calculate_return(close, 63)
        return_10d = calculate_return(close, 10)
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else close.rolling(50).mean().iloc[-1]
        last_close = float(close.iloc[-1])
        trend_raw = (0.5 if last_close > sma50 else 0.0) + (0.5 if sma50 > sma200 else 0.0)
        relative_strength_1m = return_1m - spy_1m
        relative_strength_3m = return_3m - spy_3m
        momentum_raw = 0.30 * return_1w + 0.40 * return_1m + 0.30 * return_3m
        relative_strength_raw = 0.60 * relative_strength_1m + 0.40 * relative_strength_3m
        etf = data["ticker"].iloc[-1] if "ticker" in data.columns else sector
        rows.append(
            {
                "as_of_date": as_of_date,
                "sector": sector,
                "etf": etf,
                "close": last_close,
                "return_1w": return_1w,
                "return_1m": return_1m,
                "return_3m": return_3m,
                "return_10d": return_10d,
                "relative_strength_1m": relative_strength_1m,
                "relative_strength_3m": relative_strength_3m,
                "price_above_sma50": bool(last_close > sma50),
                "sma50_above_sma200": bool(sma50 > sma200),
            }
        )
        components["momentum"][sector] = momentum_raw
        components["relative_strength"][sector] = relative_strength_raw
        components["trend"][sector] = trend_raw
        components["acceleration"][sector] = return_10d

    if not rows:
        return pd.DataFrame()

    ranks = {name: rank_normalize(values) for name, values in components.items()}
    scoring_config = config.get("sector_scoring", {})
    for row in rows:
        sector = row["sector"]
        row["momentum_rank"] = ranks["momentum"].get(sector, 0.0)
        row["relative_strength_rank"] = ranks["relative_strength"].get(sector, 0.0)
        row["trend_rank"] = ranks["trend"].get(sector, 0.0)
        row["acceleration_rank"] = ranks["acceleration"].get(sector, 0.0)
        row["sector_score"] = (
            row["momentum_rank"] * float(scoring_config.get("momentum_weight", 0.40))
            + row["relative_strength_rank"] * float(scoring_config.get("relative_strength_weight", 0.25))
            + row["trend_rank"] * float(scoring_config.get("trend_weight", 0.20))
            + row["acceleration_rank"] * float(scoring_config.get("acceleration_weight", 0.15))
        )

    result = pd.DataFrame(rows).sort_values("sector_score", ascending=False).reset_index(drop=True)
    result["sector_rank"] = range(1, len(result) + 1)
    top_sectors = int(config.get("sector_rotation", {}).get("top_sectors", 3))
    min_score = float(config.get("sector_rotation", {}).get("min_sector_score", 60))
    result["selected"] = (result["sector_rank"] <= top_sectors) & (result["sector_score"] >= min_score)
    return result


def _as_of(frame: pd.DataFrame, as_of_date) -> pd.DataFrame:
    return frame[frame["date"] <= as_of_date].copy()
