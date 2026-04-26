from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import yfinance as yf

from src.black_scholes import calculate_call_greeks
from src.models import MomentumSignal, OptionCandidate
from src.utils import calculate_dte


@dataclass(frozen=True)
class YahooOptionSelection:
    expiry: str
    options: pd.DataFrame


class YahooClient:
    def get_historical_bars(self, ticker: str, period: str = "45d") -> pd.DataFrame:
        data = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
        if data.empty:
            return pd.DataFrame()
        return data.rename(columns={column: column.lower() for column in data.columns}).reset_index()

    def get_call_candidates(self, signal: MomentumSignal, config: dict) -> list[OptionCandidate]:
        ticker_obj = yf.Ticker(signal.ticker)
        expiries = self._select_expiries(ticker_obj, config)
        if not expiries:
            return []

        candidates: list[OptionCandidate] = []
        for expiry in expiries:
            try:
                option_chain = ticker_obj.option_chain(expiry)
            except Exception as exc:
                print(f"[{signal.ticker}] Yahoo option chain unavailable for {expiry}: {exc}")
                continue

            candidates.extend(self._build_candidates_from_calls(signal, expiry, option_chain.calls, config))

        return candidates

    def _select_expiries(self, ticker_obj, config: dict) -> list[str]:
        min_dte = int(config["strategy"]["min_dte"])
        max_dte = int(config["strategy"]["max_dte"])
        expiries = []
        for expiry in ticker_obj.options:
            ib_expiry = _yahoo_expiry_to_ib(expiry)
            dte = calculate_dte(ib_expiry)
            if min_dte <= dte <= max_dte:
                expiries.append(expiry)
        return sorted(expiries)

    def _build_candidates_from_calls(
        self,
        signal: MomentumSignal,
        yahoo_expiry: str,
        calls: pd.DataFrame,
        config: dict,
    ) -> list[OptionCandidate]:
        if calls is None or calls.empty:
            return []

        strike_window_pct = float(config["options"]["strike_window_pct"])
        min_strike = signal.last_price * (1 - strike_window_pct)
        max_strike = signal.last_price * (1 + strike_window_pct)
        ib_expiry = _yahoo_expiry_to_ib(yahoo_expiry)
        dte = calculate_dte(ib_expiry)
        risk_free_rate = float(config.get("black_scholes", {}).get("risk_free_rate", 0.045))
        dividend_yield = float(config.get("black_scholes", {}).get("dividend_yield", 0.0))

        candidates: list[OptionCandidate] = []
        for row in calls.to_dict("records"):
            strike = _safe_float(row.get("strike"))
            if strike is None or not min_strike <= strike <= max_strike:
                continue

            bid = _safe_float(row.get("bid"))
            ask = _safe_float(row.get("ask"))
            implied_vol = _safe_float(row.get("impliedVolatility"))
            if bid is None or ask is None or implied_vol is None:
                continue

            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else None
            greeks = calculate_call_greeks(
                underlying_price=signal.last_price,
                strike=strike,
                dte=dte,
                implied_vol=implied_vol,
                risk_free_rate=risk_free_rate,
                dividend_yield=dividend_yield,
            )
            if greeks is None:
                continue

            candidates.append(
                OptionCandidate(
                    ticker=signal.ticker,
                    expiry=ib_expiry,
                    strike=strike,
                    right="C",
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    delta=greeks.delta,
                    gamma=greeks.gamma,
                    theta=greeks.theta,
                    vega=greeks.vega,
                    implied_vol=implied_vol,
                    open_interest=_safe_int(row.get("openInterest")),
                    dte=dte,
                    momentum_score=signal.momentum_score,
                    liquidity_score=0.0,
                    total_score=0.0,
                )
            )

        return candidates


def _yahoo_expiry_to_ib(expiry: str) -> str:
    return datetime.strptime(expiry, "%Y-%m-%d").strftime("%Y%m%d")


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
