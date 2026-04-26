from __future__ import annotations

import time
from typing import Any

import pandas as pd
from ib_insync import IB, Option, Stock, util


MARKET_DATA_TYPES = {
    "live": 1,
    "frozen": 2,
    "delayed": 3,
    "delayed_frozen": 4,
}

MARKET_DATA_PERMISSION_ERROR_CODES = {354, 10091, 10167, 10168}


class IBKRClient:
    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        market_data_type: str = "delayed",
        market_data_fallback_types: list[str] | None = None,
        market_data_generic_ticks: str = "",
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.market_data_type = market_data_type
        self.market_data_fallback_types = market_data_fallback_types or ["delayed_frozen"]
        self.market_data_generic_ticks = market_data_generic_ticks
        self._recent_market_data_errors: list[dict[str, Any]] = []
        self.ib = IB()
        self.ib.errorEvent += self._on_ib_error
        self._disable_order_submission()

    def connect(self) -> None:
        if not self.ib.isConnected():
            self.ib.connect(self.host, self.port, clientId=self.client_id)
        if not self.ib.isConnected():
            raise ConnectionError("Unable to connect to IBKR TWS/Gateway")
        self._disable_order_submission()
        self.set_market_data_type(self.market_data_type)

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()

    def set_market_data_type(self, market_data_type: str) -> None:
        type_id = _market_data_type_id(market_data_type)
        self.ib.reqMarketDataType(type_id)

    def get_stock_contract(self, ticker: str):
        contract = Stock(ticker, "SMART", "USD")
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise ValueError(f"Could not qualify stock contract for {ticker}")
        return qualified[0]

    def get_historical_bars(self, ticker: str, duration: str = "30 D", bar_size: str = "1 day") -> pd.DataFrame:
        contract = self.get_stock_contract(ticker)
        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        if not bars:
            return pd.DataFrame()
        return util.df(bars)

    def get_option_chain_definitions(self, ticker: str):
        contract = self.get_stock_contract(ticker)
        chains = self.ib.reqSecDefOptParams(ticker, "", contract.secType, contract.conId)
        return [chain for chain in chains if chain.exchange in {"SMART", "CBOE", ""}]

    def build_option_contract(self, ticker: str, expiry: str, strike: float, right: str):
        normalized_right = "C" if right.upper() in {"CALL", "C"} else right.upper()
        contract = Option(ticker, expiry, float(strike), normalized_right, "SMART", currency="USD")
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise ValueError(f"Could not qualify option contract {ticker} {expiry} {strike}{normalized_right}")
        return qualified[0]

    def get_option_market_data(self, option_contract, wait_seconds: float = 1.5) -> dict[str, Any]:
        market_data_types = [self.market_data_type, *self.market_data_fallback_types]
        for market_data_type in dict.fromkeys(market_data_types):
            self.set_market_data_type(market_data_type)
            self._clear_recent_market_data_errors()
            ticker = None
            try:
                ticker = self.ib.reqMktData(
                    option_contract,
                    genericTickList=self.market_data_generic_ticks,
                    snapshot=False,
                )
                self.ib.sleep(wait_seconds)
                market_data = self._extract_market_data(ticker)
                market_data["market_data_type"] = market_data_type
                market_data["market_data_error"] = self._latest_market_data_error_message()
                if _has_usable_market_data(market_data):
                    return market_data
            except Exception as exc:
                return _empty_market_data(market_data_type, str(exc))
            finally:
                if ticker is not None:
                    self.ib.cancelMktData(option_contract)

        return _empty_market_data(market_data_types[-1], self._latest_market_data_error_message())

    def _disable_order_submission(self) -> None:
        def blocked_place_order(*_args, **_kwargs):
            raise RuntimeError("Order submission is disabled in scanner-only V1.")

        self.ib.placeOrder = blocked_place_order

    def _on_ib_error(self, req_id: int, error_code: int, error_string: str, contract) -> None:
        if error_code not in MARKET_DATA_PERMISSION_ERROR_CODES:
            return
        self._recent_market_data_errors.append(
            {
                "req_id": req_id,
                "error_code": error_code,
                "error_string": error_string,
                "contract": contract,
                "seen_at": time.monotonic(),
            }
        )

    def _clear_recent_market_data_errors(self) -> None:
        self._recent_market_data_errors.clear()

    def _latest_market_data_error_message(self) -> str | None:
        if not self._recent_market_data_errors:
            return None
        latest = self._recent_market_data_errors[-1]
        return f"IBKR error {latest['error_code']}: {latest['error_string']}"

    def _extract_market_data(self, ticker) -> dict[str, Any]:
        bid = _none_if_nan(ticker.bid)
        ask = _none_if_nan(ticker.ask)
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        greeks = ticker.modelGreeks or ticker.bidGreeks or ticker.askGreeks or ticker.lastGreeks

        return {
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "delta": getattr(greeks, "delta", None) if greeks else None,
            "gamma": getattr(greeks, "gamma", None) if greeks else None,
            "theta": getattr(greeks, "theta", None) if greeks else None,
            "vega": getattr(greeks, "vega", None) if greeks else None,
            "implied_vol": getattr(greeks, "impliedVol", None) if greeks else None,
            "open_interest": _safe_int(getattr(ticker, "callOpenInterest", None)),
        }


def _none_if_nan(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return float(value)


def _safe_int(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _market_data_type_id(market_data_type: str) -> int:
    normalized = market_data_type.lower().replace("-", "_")
    if normalized not in MARKET_DATA_TYPES:
        valid = ", ".join(sorted(MARKET_DATA_TYPES))
        raise ValueError(f"Invalid market data type '{market_data_type}'. Valid values: {valid}")
    return MARKET_DATA_TYPES[normalized]


def _has_usable_market_data(market_data: dict[str, Any]) -> bool:
    has_quote = market_data.get("bid") is not None and market_data.get("ask") is not None
    has_greeks = market_data.get("delta") is not None and market_data.get("theta") is not None
    return has_quote or has_greeks


def _empty_market_data(market_data_type: str, error: str | None = None) -> dict[str, Any]:
    return {
        "bid": None,
        "ask": None,
        "mid": None,
        "delta": None,
        "gamma": None,
        "theta": None,
        "vega": None,
        "implied_vol": None,
        "open_interest": None,
        "market_data_type": market_data_type,
        "market_data_error": error,
    }
