from __future__ import annotations

import pandas as pd

from src.sector_rotation.sector_scoring import calculate_return, rank_normalize


def calculate_stock_scores(
    stock_price_data: dict[str, pd.DataFrame],
    sector_price_data: dict[str, pd.DataFrame],
    sector_map: pd.DataFrame,
    selected_sectors: list[str],
    as_of_date,
    config: dict,
) -> pd.DataFrame:
    as_of_date = pd.Timestamp(as_of_date).date()
    rows = []
    stock_config = config.get("stock_scoring", {})

    for record in sector_map[sector_map["sector"].isin(selected_sectors)].to_dict("records"):
        ticker = record["ticker"]
        sector = record["sector"]
        sector_etf = record["sector_etf"]
        stock_frame = stock_price_data.get(ticker)
        sector_frame = sector_price_data.get(sector)
        if stock_frame is None or sector_frame is None:
            continue
        stock = stock_frame[stock_frame["date"] <= as_of_date].copy()
        sector_data = sector_frame[sector_frame["date"] <= as_of_date].copy()
        if len(stock) < 64 or len(sector_data) < 64:
            continue
        close = stock["close"]
        sector_close = sector_data["close"]
        return_1w = calculate_return(close, 5)
        return_1m = calculate_return(close, 21)
        return_3m = calculate_return(close, 63)
        sector_1m = calculate_return(sector_close, 21)
        sector_3m = calculate_return(sector_close, 63)
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else sma50
        last_close = float(close.iloc[-1])
        average_dollar_volume = float((stock["close"] * stock["volume"]).tail(20).mean())
        if average_dollar_volume < float(stock_config.get("min_average_dollar_volume", 50_000_000)):
            continue
        trend_raw = (0.5 if last_close > sma50 else 0.0) + (0.5 if sma50 > sma200 else 0.0)
        rs_1m = return_1m - sector_1m
        rs_3m = return_3m - sector_3m
        rows.append(
            {
                "as_of_date": as_of_date,
                "ticker": ticker,
                "sector": sector,
                "sector_etf": sector_etf,
                "close": last_close,
                "return_1w": return_1w,
                "return_1m": return_1m,
                "return_3m": return_3m,
                "relative_strength_vs_sector_1m": rs_1m,
                "relative_strength_vs_sector_3m": rs_3m,
                "close_above_sma50": bool(last_close > sma50),
                "sma50_above_sma200": bool(sma50 > sma200),
                "average_dollar_volume_20d": average_dollar_volume,
                "_momentum_raw": 0.30 * return_1w + 0.40 * return_1m + 0.30 * return_3m,
                "_rs_raw": 0.60 * rs_1m + 0.40 * rs_3m,
                "_trend_raw": trend_raw,
                "_liquidity_raw": average_dollar_volume,
            }
        )

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    ranked_frames = []
    for sector, group in result.groupby("sector", group_keys=False):
        group = group.copy()
        momentum = rank_normalize(dict(zip(group["ticker"], group["_momentum_raw"])))
        rs = rank_normalize(dict(zip(group["ticker"], group["_rs_raw"])))
        trend = rank_normalize(dict(zip(group["ticker"], group["_trend_raw"])))
        liquidity = rank_normalize(dict(zip(group["ticker"], group["_liquidity_raw"])))
        group["momentum_rank"] = group["ticker"].map(momentum)
        group["rs_vs_sector_rank"] = group["ticker"].map(rs)
        group["trend_rank"] = group["ticker"].map(trend)
        group["liquidity_rank"] = group["ticker"].map(liquidity)
        group["stock_score"] = (
            group["rs_vs_sector_rank"] * float(stock_config.get("relative_strength_vs_sector_weight", 0.35))
            + group["momentum_rank"] * float(stock_config.get("momentum_weight", 0.30))
            + group["trend_rank"] * float(stock_config.get("trend_weight", 0.20))
            + group["liquidity_rank"] * float(stock_config.get("liquidity_weight", 0.15))
        )
        group = group.sort_values("stock_score", ascending=False).reset_index(drop=True)
        group["stock_rank_within_sector"] = range(1, len(group) + 1)
        ranked_frames.append(group)

    output = pd.concat(ranked_frames, ignore_index=True)
    min_score = float(config.get("sector_rotation", {}).get("min_stock_score", 55))
    top_stocks = int(config.get("sector_rotation", {}).get("top_stocks_per_sector", 5))
    output["selected"] = (output["stock_rank_within_sector"] <= top_stocks) & (output["stock_score"] >= min_score)
    return output.drop(columns=["_momentum_raw", "_rs_raw", "_trend_raw", "_liquidity_raw"])
