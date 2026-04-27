from __future__ import annotations

import json

import pandas as pd

from src.utils import ensure_parent_dir


COMPARISON_FIELDS = [
    "total_pnl",
    "return_pct",
    "total_trades",
    "win_rate",
    "average_win",
    "average_loss",
    "profit_factor",
    "max_drawdown",
    "average_holding_days",
    "average_trades_per_day",
    "max_trades_in_one_day",
    "return_per_trade",
    "pnl_per_day",
]


def compare_backtest_results(daily_summary: dict, mtf_summary: dict) -> dict:
    comparison = {
        "daily": _summary_subset(daily_summary),
        "multi_timeframe": _summary_subset(mtf_summary),
    }
    daily_dd = abs(float(daily_summary.get("max_drawdown", 0.0)))
    mtf_dd = abs(float(mtf_summary.get("max_drawdown", 0.0)))
    daily_profit_factor = float(daily_summary.get("profit_factor", 0.0))
    mtf_profit_factor = float(mtf_summary.get("profit_factor", 0.0))
    daily_trades = int(daily_summary.get("total_trades", 0))
    mtf_trades = int(mtf_summary.get("total_trades", 0))
    daily_rpt = float(daily_summary.get("return_per_trade", daily_summary.get("average_pnl", 0.0)))
    mtf_rpt = float(mtf_summary.get("return_per_trade", mtf_summary.get("average_pnl", 0.0)))

    comparison["assessment"] = {
        "mtf_reduced_drawdown": mtf_dd < daily_dd,
        "mtf_improved_profit_factor": mtf_profit_factor > daily_profit_factor,
        "mtf_overtrading_warning": mtf_trades > daily_trades * 2 and mtf_rpt < daily_rpt,
    }
    return comparison


def save_comparison_outputs(comparison: dict, csv_path: str, json_path: str) -> None:
    ensure_parent_dir(csv_path)
    rows = []
    for mode in ["daily", "multi_timeframe"]:
        row = {"mode": mode}
        row.update(comparison[mode])
        rows.append(row)
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    ensure_parent_dir(json_path)
    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(comparison, file, indent=2)


def _summary_subset(summary: dict) -> dict:
    result = {field: summary.get(field, 0.0) for field in COMPARISON_FIELDS}
    if "return_pct" not in summary:
        initial = float(summary.get("ending_capital", 0.0)) - float(summary.get("total_pnl", 0.0))
        result["return_pct"] = float(summary.get("total_pnl", 0.0)) / initial if initial else 0.0
    return result
