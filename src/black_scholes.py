from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm


@dataclass(frozen=True)
class BlackScholesGreeks:
    delta: float
    gamma: float
    theta: float
    vega: float


def calculate_call_greeks(
    underlying_price: float,
    strike: float,
    dte: int,
    implied_vol: float,
    risk_free_rate: float = 0.045,
    dividend_yield: float = 0.0,
) -> BlackScholesGreeks | None:
    if underlying_price <= 0 or strike <= 0 or dte <= 0 or implied_vol <= 0:
        return None

    time_to_expiry = dte / 365.0
    sqrt_time = math.sqrt(time_to_expiry)
    d1 = (
        math.log(underlying_price / strike)
        + (risk_free_rate - dividend_yield + 0.5 * implied_vol**2) * time_to_expiry
    ) / (implied_vol * sqrt_time)
    d2 = d1 - implied_vol * sqrt_time

    dividend_discount = math.exp(-dividend_yield * time_to_expiry)
    rate_discount = math.exp(-risk_free_rate * time_to_expiry)

    delta = dividend_discount * norm.cdf(d1)
    gamma = dividend_discount * norm.pdf(d1) / (underlying_price * implied_vol * sqrt_time)
    annual_theta = (
        -(underlying_price * dividend_discount * norm.pdf(d1) * implied_vol) / (2 * sqrt_time)
        - risk_free_rate * strike * rate_discount * norm.cdf(d2)
        + dividend_yield * underlying_price * dividend_discount * norm.cdf(d1)
    )
    theta = annual_theta / 365.0
    vega = underlying_price * dividend_discount * norm.pdf(d1) * sqrt_time / 100.0

    return BlackScholesGreeks(
        delta=float(delta),
        gamma=float(gamma),
        theta=float(theta),
        vega=float(vega),
    )
