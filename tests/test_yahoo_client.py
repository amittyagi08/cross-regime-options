from datetime import date, timedelta

import pandas as pd

from src.models import MomentumSignal
from src.yahoo_client import YahooClient


CONFIG = {
    "strategy": {"min_dte": 7, "max_dte": 45},
    "options": {"strike_window_pct": 0.10},
    "black_scholes": {"risk_free_rate": 0.05, "dividend_yield": 0.0},
}


def test_build_candidates_from_yahoo_calls_computes_greeks():
    client = YahooClient()
    signal = MomentumSignal(
        ticker="AAPL",
        last_price=100.0,
        momentum_score=0.05,
        return_5d=0.02,
        return_10d=0.03,
        volume_ratio=1.1,
    )
    calls = pd.DataFrame(
        [
            {
                "strike": 100,
                "bid": 4.9,
                "ask": 5.1,
                "impliedVolatility": 0.25,
                "openInterest": 500,
            },
            {
                "strike": 130,
                "bid": 0.1,
                "ask": 0.2,
                "impliedVolatility": 0.30,
                "openInterest": 10,
            },
        ]
    )

    yahoo_expiry = (date.today() + timedelta(days=30)).isoformat()
    ib_expiry = yahoo_expiry.replace("-", "")

    candidates = client._build_candidates_from_calls(signal, yahoo_expiry, calls, CONFIG)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.expiry == ib_expiry
    assert candidate.mid == 5.0
    assert candidate.delta is not None
    assert candidate.theta is not None
