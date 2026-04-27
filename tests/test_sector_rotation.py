from datetime import date

import pandas as pd

from src.backtest.comparison import compare_static_vs_sector_rotation
from src.sector_rotation.rebalance import get_effective_rebalance_date, get_rebalance_dates
from src.sector_rotation.sector_scoring import rank_normalize
from src.sector_rotation.universe_builder import build_weekly_universe


def test_rank_normalize_scales_to_percent_ranks():
    ranks = rank_normalize({"A": 1.0, "B": 2.0, "C": 3.0})

    assert ranks["C"] == 100.0
    assert ranks["A"] < ranks["B"] < ranks["C"]


def test_rebalance_uses_next_available_trading_day():
    prices = pd.DataFrame({"date": [date(2026, 1, 6), date(2026, 1, 7)]})

    assert get_effective_rebalance_date(prices, date(2026, 1, 5)) == date(2026, 1, 6)


def test_get_rebalance_dates_returns_weekly_dates():
    dates = get_rebalance_dates("2026-01-01", "2026-01-15", "W-MON")

    assert dates == [date(2026, 1, 5), date(2026, 1, 12)]


def test_build_weekly_universe_filters_sector_and_stock_scores():
    sector_scores = pd.DataFrame(
        [
            {"sector": "Tech", "sector_etf": "XLK", "sector_score": 80, "sector_rank": 1},
            {"sector": "Energy", "sector_etf": "XLE", "sector_score": 50, "sector_rank": 2},
        ]
    )
    stock_scores = pd.DataFrame(
        [
            {"ticker": "MSFT", "sector": "Tech", "sector_etf": "XLK", "stock_score": 70, "stock_rank_within_sector": 1},
            {"ticker": "AAPL", "sector": "Tech", "sector_etf": "XLK", "stock_score": 40, "stock_rank_within_sector": 2},
        ]
    )
    config = {
        "sector_rotation": {
            "top_sectors": 1,
            "top_stocks_per_sector": 2,
            "min_sector_score": 60,
            "min_stock_score": 55,
        }
    }

    universe = build_weekly_universe(date(2026, 1, 5), sector_scores, stock_scores, config)

    assert universe["ticker"].tolist() == ["MSFT"]


def test_sector_comparison_flags():
    comparison = compare_static_vs_sector_rotation(
        {"total_pnl": 100, "max_drawdown": -200, "profit_factor": 1.0, "total_trades": 5, "return_per_trade": 20},
        {"total_pnl": 200, "max_drawdown": -100, "profit_factor": 1.5, "total_trades": 6, "return_per_trade": 33},
    )

    assert comparison["assessment"]["sector_rotation_improved_return"] is True
    assert comparison["assessment"]["sector_rotation_reduced_drawdown"] is True
    assert comparison["assessment"]["sector_rotation_improved_profit_factor"] is True
