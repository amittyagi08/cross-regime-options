from src.black_scholes import calculate_call_greeks


def test_call_greeks_are_reasonable_for_atm_call():
    greeks = calculate_call_greeks(
        underlying_price=100,
        strike=100,
        dte=30,
        implied_vol=0.20,
        risk_free_rate=0.05,
        dividend_yield=0.0,
    )

    assert greeks is not None
    assert 0.50 < greeks.delta < 0.60
    assert greeks.gamma > 0
    assert greeks.theta < 0
    assert greeks.vega > 0


def test_call_greeks_return_none_for_invalid_inputs():
    assert calculate_call_greeks(100, 100, 0, 0.20) is None
    assert calculate_call_greeks(100, 100, 30, 0) is None
