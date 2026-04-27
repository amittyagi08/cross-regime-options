from __future__ import annotations

import pandas as pd


def build_weekly_universe(
    as_of_date,
    sector_scores: pd.DataFrame,
    stock_scores: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    rotation = config.get("sector_rotation", {})
    selected_sectors = sector_scores[
        (sector_scores["sector_rank"] <= int(rotation.get("top_sectors", 3)))
        & (sector_scores["sector_score"] >= float(rotation.get("min_sector_score", 60)))
    ]
    selected_stocks = stock_scores[
        (stock_scores["sector"].isin(selected_sectors["sector"]))
        & (stock_scores["stock_rank_within_sector"] <= int(rotation.get("top_stocks_per_sector", 5)))
        & (stock_scores["stock_score"] >= float(rotation.get("min_stock_score", 55)))
    ]
    if selected_stocks.empty:
        return pd.DataFrame(
            columns=[
                "week_start",
                "sector",
                "sector_etf",
                "sector_score",
                "sector_rank",
                "ticker",
                "stock_score",
                "stock_rank_within_sector",
            ]
        )
    result = selected_stocks.merge(
        selected_sectors[["sector", "sector_score", "sector_rank"]],
        on="sector",
        how="left",
    )
    result["week_start"] = pd.Timestamp(as_of_date).date()
    return result[
        [
            "week_start",
            "sector",
            "sector_etf",
            "sector_score",
            "sector_rank",
            "ticker",
            "stock_score",
            "stock_rank_within_sector",
        ]
    ].sort_values(["sector_rank", "stock_rank_within_sector"])
