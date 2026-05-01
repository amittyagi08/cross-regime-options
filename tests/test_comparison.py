from src.backtest.comparison import compare_backtest_results, compare_v4_vs_v41_risk


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


def test_compare_v4_vs_v41_risk_flags():
    base = {
        "total_pnl": 1000,
        "total_trades": 100,
        "profit_factor": 1.4,
        "max_drawdown": -1000,
        "return_to_drawdown_ratio": 1.0,
    }
    risk = {
        "total_pnl": 900,
        "total_trades": 80,
        "profit_factor": 1.6,
        "max_drawdown": -700,
        "return_to_drawdown_ratio": 1.285,
    }

    comparison = compare_v4_vs_v41_risk(base, risk)

    assert comparison["assessment"]["risk_reduced_drawdown"] is True
    assert comparison["assessment"]["risk_improved_profit_factor"] is True
    assert comparison["assessment"]["risk_improved_return_to_drawdown"] is True
    assert comparison["assessment"]["risk_preserved_trade_count"] is True
    assert comparison["assessment"]["risk_preserved_edge"] is True
