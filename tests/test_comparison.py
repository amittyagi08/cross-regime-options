from src.backtest.comparison import compare_backtest_results


def test_comparison_flags_drawdown_profit_factor_and_overtrading():
    daily = {
        "total_pnl": 1000,
        "total_trades": 10,
        "profit_factor": 1.5,
        "max_drawdown": -500,
        "return_per_trade": 100,
    }
    mtf = {
        "total_pnl": 1200,
        "total_trades": 25,
        "profit_factor": 2.0,
        "max_drawdown": -300,
        "return_per_trade": 50,
    }

    comparison = compare_backtest_results(daily, mtf)

    assert comparison["assessment"]["mtf_reduced_drawdown"] is True
    assert comparison["assessment"]["mtf_improved_profit_factor"] is True
    assert comparison["assessment"]["mtf_overtrading_warning"] is True
