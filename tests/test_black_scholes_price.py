from src.backtest.synthetic_options import black_scholes_call_price


def test_call_price_is_positive():
    price = black_scholes_call_price(100, 100, 30 / 365, 0.05, 0.20)

    assert price > 0


def test_higher_underlying_increases_call_price():
    lower = black_scholes_call_price(95, 100, 30 / 365, 0.05, 0.20)
    higher = black_scholes_call_price(105, 100, 30 / 365, 0.05, 0.20)

    assert higher > lower


def test_higher_volatility_increases_call_price():
    lower = black_scholes_call_price(100, 100, 30 / 365, 0.05, 0.20)
    higher = black_scholes_call_price(100, 100, 30 / 365, 0.05, 0.40)

    assert higher > lower
