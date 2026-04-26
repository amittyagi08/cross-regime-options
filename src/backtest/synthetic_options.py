from __future__ import annotations

import math
from datetime import date, timedelta

from scipy.stats import norm

from src.black_scholes import calculate_call_greeks
from src.models import OptionCandidate


def black_scholes_call_price(
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> float:
    if s <= 0 or k <= 0 or t <= 0 or sigma <= 0:
        return max(0.0, s - k)

    sqrt_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma**2) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return float(s * math.exp(-q * t) * norm.cdf(d1) - k * math.exp(-r * t) * norm.cdf(d2))


def generate_synthetic_call_candidates(
    ticker: str,
    trade_date: date,
    underlying_price: float,
    volatility: float,
    momentum_score: float,
    config: dict,
) -> list[OptionCandidate]:
    synthetic_config = config.get("synthetic_options", {})
    min_dte = int(synthetic_config.get("min_dte", 14))
    max_dte = int(synthetic_config.get("max_dte", 30))
    target_delta = float(synthetic_config.get("target_delta", 0.60))
    min_delta = float(synthetic_config.get("min_delta", 0.50))
    max_delta = float(synthetic_config.get("max_delta", 0.70))
    strike_step = float(synthetic_config.get("strike_step", 5))
    risk_free_rate = float(synthetic_config.get("risk_free_rate", 0.045))
    dividend_yield = float(synthetic_config.get("dividend_yield", 0.0))

    candidates: list[OptionCandidate] = []
    for dte in range(min_dte, max_dte + 1):
        expiry = (trade_date + timedelta(days=dte)).strftime("%Y%m%d")
        for strike in _strike_range(underlying_price, strike_step):
            t = dte / 365.0
            price = black_scholes_call_price(
                s=underlying_price,
                k=strike,
                t=t,
                r=risk_free_rate,
                sigma=volatility,
                q=dividend_yield,
            )
            greeks = calculate_call_greeks(
                underlying_price=underlying_price,
                strike=strike,
                dte=dte,
                implied_vol=volatility,
                risk_free_rate=risk_free_rate,
                dividend_yield=dividend_yield,
            )
            if greeks is None or not min_delta <= greeks.delta <= max_delta:
                continue

            candidates.append(
                OptionCandidate(
                    ticker=ticker,
                    expiry=expiry,
                    strike=float(strike),
                    right="C",
                    bid=price * 0.995,
                    ask=price * 1.005,
                    mid=price,
                    delta=greeks.delta,
                    gamma=greeks.gamma,
                    theta=greeks.theta,
                    vega=greeks.vega,
                    implied_vol=volatility,
                    open_interest=None,
                    dte=dte,
                    momentum_score=momentum_score,
                    liquidity_score=0.0,
                    total_score=0.0,
                )
            )

    return sorted(candidates, key=lambda candidate: abs((candidate.delta or 0) - target_delta))


def reprice_synthetic_call(
    underlying_price: float,
    strike: float,
    remaining_dte: int,
    volatility: float,
    config: dict,
) -> float:
    if remaining_dte <= 0:
        return max(0.0, underlying_price - strike)

    synthetic_config = config.get("synthetic_options", {})
    return black_scholes_call_price(
        s=underlying_price,
        k=strike,
        t=max(remaining_dte, 1) / 365.0,
        r=float(synthetic_config.get("risk_free_rate", 0.045)),
        sigma=volatility,
        q=float(synthetic_config.get("dividend_yield", 0.0)),
    )


def _strike_range(underlying_price: float, strike_step: float) -> list[float]:
    low = math.floor((underlying_price * 0.85) / strike_step) * strike_step
    high = math.ceil((underlying_price * 1.15) / strike_step) * strike_step
    count = int(round((high - low) / strike_step)) + 1
    return [round(low + index * strike_step, 2) for index in range(count)]
