from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from src.black_scholes import calculate_call_greeks
from src.live.live_config import assert_live_safety
from src.live.live_data_provider import LiveDataProvider
from src.live.signal_snapshot import (
    LiveSignalSnapshot,
    OptionDiagnostic,
    OptionSignal,
    RiskDecision,
    SectorSignal,
    StockSignal,
)
from src.sector_rotation.sector_config import load_sector_etfs, load_sector_map
from src.sector_rotation.sector_scoring import calculate_sector_scores
from src.sector_rotation.stock_scoring import calculate_stock_scores
from src.utils import calculate_dte, ensure_parent_dir


class LiveSignalService:
    def __init__(self, config: dict):
        assert_live_safety(config)
        self.config = config
        live = config.get("live", {})
        self.provider = str(live.get("provider", "yahoo")).lower()
        self.data_provider = LiveDataProvider(self.provider)

    def run_live_scan(self) -> LiveSignalSnapshot:
        print("scan_started")
        print("Data provider: Yahoo. Data may be delayed or incomplete. Validate on trading platform before any trade.")
        try:
            snapshot = self._build_snapshot()
            if bool(self.config.get("live", {}).get("save_snapshots", True)):
                save_snapshot(snapshot, self.config)
            print("scan_completed")
            return snapshot
        except Exception:
            print("scan_failed")
            raise

    def _build_snapshot(self) -> LiveSignalSnapshot:
        sector_etfs = load_sector_etfs()
        sector_map = load_sector_map()
        as_of = date.today()

        sector_price_data = {
            row["sector"]: self.data_provider.get_price_history(row["etf"], period="2y", interval="1d")
            for row in sector_etfs.to_dict("records")
        }
        sector_price_data = {sector: frame for sector, frame in sector_price_data.items() if not frame.empty}

        benchmark_symbol = self.config.get("sector_rotation", {}).get("benchmark_symbol", "SPY")
        benchmark_data = self.data_provider.get_price_history(benchmark_symbol, period="2y", interval="1d")
        sector_scores = calculate_sector_scores(sector_price_data, benchmark_data, as_of, self.config)

        selected_sectors = sector_scores[sector_scores["selected"] == True]["sector"].tolist() if not sector_scores.empty else []
        selected_tickers = sector_map[sector_map["sector"].isin(selected_sectors)]["ticker"].drop_duplicates().tolist()
        stock_price_data = {
            ticker: self.data_provider.get_price_history(ticker, period="2y", interval="1d")
            for ticker in selected_tickers
        }
        stock_price_data = {ticker: frame for ticker, frame in stock_price_data.items() if not frame.empty}
        stock_scores = calculate_stock_scores(stock_price_data, sector_price_data, sector_map, selected_sectors, as_of, self.config)

        sectors = _sector_signals(sector_scores)
        universe = _stock_signals(stock_scores)
        selected_universe = [signal for signal in universe if signal.selected]
        options, option_diagnostics = self._option_signals(selected_universe)
        risk = _risk_decisions(selected_universe, options, option_diagnostics, self.config)
        regime_status = _regime_status(benchmark_data)

        return LiveSignalSnapshot(
            as_of=self.data_provider.get_market_timestamp(),
            provider=self.provider,
            market_status="validation",
            regime_status=regime_status,
            sectors=sectors,
            universe=universe,
            options=options,
            option_diagnostics=option_diagnostics,
            risk=risk,
        )

    def _option_signals(self, universe: list[StockSignal]) -> tuple[list[OptionSignal], list[OptionDiagnostic]]:
        max_contracts = int(self.config.get("dashboard", {}).get("max_contracts_per_ticker", 3))
        output: list[OptionSignal] = []
        diagnostics: list[OptionDiagnostic] = []
        for stock in universe:
            candidates, diagnostic = _scan_live_yahoo_options(stock, self.config)
            diagnostics.append(diagnostic)
            ranked = sorted(candidates, key=lambda candidate: candidate.total_score, reverse=True)
            output.extend(ranked[:max_contracts])
        return sorted(output, key=lambda candidate: candidate.total_score, reverse=True), diagnostics


def save_snapshot(snapshot: LiveSignalSnapshot, config: dict) -> None:
    live = config.get("live", {})
    json_path = live.get("snapshot_json_path", "output/live_signal_snapshot.json")
    csv_path = live.get("snapshot_csv_path", "output/live_signal_snapshot.csv")

    ensure_parent_dir(json_path)
    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(snapshot.to_dict(), file, indent=2)

    ensure_parent_dir(csv_path)
    rows = []
    for section in ["sectors", "universe", "options", "option_diagnostics", "risk"]:
        for item in getattr(snapshot, section):
            row = {"section": section}
            row.update(asdict(item))
            rows.append(row)
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    _append_log("snapshot_saved", config)
    print("snapshot_saved")


def load_latest_snapshot(config: dict) -> LiveSignalSnapshot | None:
    path = Path(config.get("live", {}).get("snapshot_json_path", "output/live_signal_snapshot.json"))
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return LiveSignalSnapshot(
        as_of=data.get("as_of", ""),
        provider=data.get("provider", "yahoo"),
        market_status=data.get("market_status", "validation"),
        regime_status=data.get("regime_status", "unknown"),
        sectors=[SectorSignal(**item) for item in data.get("sectors", [])],
        universe=[StockSignal(**item) for item in data.get("universe", [])],
        options=[_load_option_signal(item) for item in data.get("options", [])],
        option_diagnostics=[OptionDiagnostic(**item) for item in data.get("option_diagnostics", [])],
        risk=[RiskDecision(**item) for item in data.get("risk", [])],
        warning=data.get("warning", LiveSignalSnapshot(as_of="", provider="", market_status="", regime_status="").warning),
    )


def _load_option_signal(item: dict) -> OptionSignal:
    data = dict(item)
    data.setdefault("gamma", None)
    data.setdefault("vega", None)
    data.setdefault("quote_quality", "live")
    data.setdefault("score_breakdown", {})
    data.setdefault("score_details", "")
    data.setdefault("momentum_score", data.get("score_breakdown", {}).get("momentum_score", 0.5))
    data.setdefault("liquidity_score", data.get("score_breakdown", {}).get("liquidity_score", 0.5))
    data.setdefault("theta_efficiency_score", data.get("score_breakdown", {}).get("theta_efficiency_score", 0.5))
    data.setdefault("delta_score", data.get("score_breakdown", {}).get("delta_score", 0.5))
    data.setdefault("iv_score", data.get("score_breakdown", {}).get("iv_score", 0.5))
    data.setdefault("dte_score", data.get("score_breakdown", {}).get("dte_score", 0.5))
    return OptionSignal(**data)


def _sector_signals(scores: pd.DataFrame) -> list[SectorSignal]:
    if scores.empty:
        return []
    return [
        SectorSignal(
            as_of=str(row.get("as_of_date", "")),
            sector=str(row["sector"]),
            etf=str(row["etf"]),
            sector_score=float(row["sector_score"]),
            sector_rank=int(row["sector_rank"]),
            selected=bool(row["selected"]),
            return_1w=float(row["return_1w"]),
            return_1m=float(row["return_1m"]),
            return_3m=float(row["return_3m"]),
        )
        for row in scores.to_dict("records")
    ]


def _stock_signals(scores: pd.DataFrame) -> list[StockSignal]:
    if scores.empty:
        return []
    return [
        StockSignal(
            ticker=str(row["ticker"]),
            sector=str(row["sector"]),
            stock_score=float(row["stock_score"]),
            stock_rank=int(row["stock_rank_within_sector"]),
            selected=bool(row["selected"]),
            last_price=float(row["close"]),
            momentum_score=float(row["momentum_rank"]) / 100,
        )
        for row in scores.to_dict("records")
    ]


def _risk_decisions(
    universe: list[StockSignal],
    options: list[OptionSignal],
    option_diagnostics: list[OptionDiagnostic],
    config: dict,
) -> list[RiskDecision]:
    option_tickers = {option.ticker for option in options}
    diagnostics_by_ticker = {diagnostic.ticker: diagnostic for diagnostic in option_diagnostics}
    multiplier = 1.0
    reason_size = "RISK_ALLOWED"
    if bool(config.get("risk_controls", {}).get("enabled", True)):
        multiplier = float(config.get("risk_controls", {}).get("reduced_position_size_pct", 0.85))
        reason_size = "RISK_SIZE_LIMIT_APPLIED"
    decisions = []
    for stock in universe:
        reason_codes = ["SECTOR_SELECTED", "STOCK_MOMENTUM_VALID"]
        allowed = stock.ticker in option_tickers
        if allowed:
            reason_codes.extend(["OPTION_DELTA_VALID", "OPTION_LIQUIDITY_VALID", reason_size])
            notes = "Signal is eligible for manual validation. No order placement is available."
        else:
            diagnostic = diagnostics_by_ticker.get(stock.ticker)
            reason_codes.extend(["RISK_BLOCKED_NO_VALID_OPTION", diagnostic.failure_reason if diagnostic else "NO_OPTION_DIAGNOSTIC"])
            notes = diagnostic.notes if diagnostic else "Blocked until a valid option contract is available."
        decisions.append(
            RiskDecision(
                ticker=stock.ticker,
                allowed=allowed,
                reason_codes=reason_codes,
                position_size_multiplier=multiplier if allowed else 0.0,
                notes=notes,
            )
        )
    return decisions


def _scan_live_yahoo_options(stock: StockSignal, config: dict) -> tuple[list[OptionSignal], OptionDiagnostic]:
    filters = _live_option_filters(config)
    available_expiries: list[str] = []
    selected_expiries: list[str] = []
    calls_before = 0
    after_strike: list[dict] = []
    after_quote: list[dict] = []
    after_iv: list[dict] = []
    after_greeks: list[OptionSignal] = []
    failure_reason: str | None = None

    try:
        yahoo_stock = yf.Ticker(stock.ticker)
        available_expiries = list(yahoo_stock.options or [])
        if not available_expiries:
            failure_reason = "NO_EXPIRIES"
        else:
            selected_expiries = [
                expiry
                for expiry in available_expiries
                if filters["min_dte"] <= _dte_from_yahoo_expiry(expiry) <= filters["max_dte"]
            ]
            if not selected_expiries:
                failure_reason = "NO_EXPIRY_IN_DTE_RANGE"

        for expiry in selected_expiries:
            chain = yahoo_stock.option_chain(expiry)
            calls = _normalize_yahoo_calls(chain.calls)
            calls_before += len(calls)
            if calls.empty:
                continue

            strike_filtered = _filter_strike_window(calls, stock.last_price, filters["strike_window_pct"])
            after_strike.extend(strike_filtered.to_dict("records"))
            quote_filtered = [_with_live_quote(row) for row in strike_filtered.to_dict("records")]
            quote_filtered = [row for row in quote_filtered if row is not None]
            after_quote.extend(quote_filtered)
            iv_filtered = [row for row in quote_filtered if _safe_float(row.get("impliedVolatility")) and _safe_float(row.get("impliedVolatility")) > 0]
            after_iv.extend(iv_filtered)

            raw_candidates = []
            for row in iv_filtered:
                raw_candidate = _build_live_option_candidate(stock, expiry, row, filters, config)
                if raw_candidate is not None:
                    raw_candidates.append(raw_candidate)
            after_greeks.extend(_score_live_option_candidates(raw_candidates))

        if failure_reason is None:
            if calls_before == 0:
                failure_reason = "NO_CALLS_FROM_PROVIDER"
            elif not after_strike:
                failure_reason = "ALL_CALLS_FAILED_STRIKE_FILTER"
            elif not after_quote:
                failure_reason = "ALL_CALLS_FAILED_QUOTE_FILTER"
            elif not after_iv or not after_greeks:
                failure_reason = "ALL_CALLS_FAILED_GREEKS_FILTER"

    except Exception as exc:
        failure_reason = "NO_CALLS_FROM_PROVIDER"
        print(f"[{stock.ticker}] Yahoo option diagnostic error: {exc}")

    if after_greeks:
        failure_reason = None

    diagnostic = OptionDiagnostic(
        ticker=stock.ticker,
        last_price=stock.last_price,
        available_expiries=available_expiries,
        selected_expiries=selected_expiries,
        calls_before_filters=calls_before,
        after_strike_filter=len(after_strike),
        after_quote_filter=len(after_quote),
        after_iv_filter=len(after_iv),
        after_greeks_filter=len(after_greeks),
        failure_reason=failure_reason,
        notes=_diagnostic_notes(failure_reason),
    )
    _print_option_diagnostic(diagnostic)
    return after_greeks, diagnostic


def _live_option_filters(config: dict) -> dict:
    options = config.get("options", {})
    return {
        "min_dte": int(config.get("live_options", {}).get("min_dte", 7)),
        "max_dte": int(config.get("live_options", {}).get("max_dte", 45)),
        "min_delta": float(config.get("live_options", {}).get("min_delta", 0.45)),
        "max_delta": float(config.get("live_options", {}).get("max_delta", 0.75)),
        "max_bid_ask_spread_pct": float(config.get("live_options", {}).get("max_bid_ask_spread_pct", 0.20)),
        "min_open_interest": int(config.get("live_options", {}).get("min_open_interest", 0)),
        "strike_window_pct": float(config.get("live_options", {}).get("strike_window_pct", options.get("strike_window_pct", 0.10))),
    }


def _normalize_yahoo_calls(calls: pd.DataFrame) -> pd.DataFrame:
    required = ["contractSymbol", "strike", "bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility"]
    if calls is None or calls.empty:
        return pd.DataFrame(columns=required)
    frame = calls.copy()
    for column in required:
        if column not in frame.columns:
            frame[column] = None
    return frame[required]


def _filter_strike_window(calls: pd.DataFrame, last_price: float, strike_window_pct: float) -> pd.DataFrame:
    min_strike = last_price * (1 - strike_window_pct)
    max_strike = last_price * (1 + strike_window_pct)
    strikes = pd.to_numeric(calls["strike"], errors="coerce")
    return calls[(strikes >= min_strike) & (strikes <= max_strike)].copy()


def _with_live_quote(row: dict) -> dict | None:
    bid = _safe_float(row.get("bid")) or 0.0
    ask = _safe_float(row.get("ask")) or 0.0
    last_price = _safe_float(row.get("lastPrice")) or 0.0
    row = dict(row)
    if bid > 0 and ask > 0:
        row["mid"] = (bid + ask) / 2
        row["quote_quality"] = "live"
        return row
    if last_price > 0:
        row["bid"] = max(0.01, last_price * 0.95)
        row["ask"] = last_price * 1.05
        row["mid"] = last_price
        row["quote_quality"] = "fallback"
        return row
    return None


def _build_live_option_candidate(stock: StockSignal, yahoo_expiry: str, row: dict, filters: dict, config: dict) -> dict | None:
    strike = _safe_float(row.get("strike"))
    implied_vol = _safe_float(row.get("impliedVolatility"))
    if strike is None or implied_vol is None or implied_vol <= 0:
        return None
    ib_expiry = _yahoo_expiry_to_ib(yahoo_expiry)
    dte = calculate_dte(ib_expiry)
    greeks = calculate_call_greeks(
        underlying_price=stock.last_price,
        strike=strike,
        dte=dte,
        implied_vol=implied_vol,
        risk_free_rate=float(config.get("black_scholes", {}).get("risk_free_rate", 0.045)),
        dividend_yield=float(config.get("black_scholes", {}).get("dividend_yield", 0.0)),
    )
    delta = greeks.delta if greeks is not None else None
    theta = greeks.theta if greeks is not None else None
    gamma = greeks.gamma if greeks is not None else None
    vega = greeks.vega if greeks is not None else None

    bid = float(row["bid"])
    ask = float(row["ask"])
    mid = float(row["mid"])
    open_interest = _safe_int(row.get("openInterest"))
    contract_symbol = str(row.get("contractSymbol") or f"{stock.ticker} {ib_expiry} {strike:g}C")
    return {
        "ticker": stock.ticker,
        "contract_symbol": contract_symbol,
        "expiry": ib_expiry,
        "strike": strike,
        "right": "C",
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "implied_vol": implied_vol,
        "open_interest": open_interest,
        "dte": dte,
        "quote_quality": str(row.get("quote_quality", "live")),
        "underlying_momentum_score": get_underlying_momentum_score(stock),
    }


def _dte_from_yahoo_expiry(expiry: str) -> int:
    return (datetime.strptime(expiry, "%Y-%m-%d").date() - date.today()).days


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


def _diagnostic_notes(reason: str | None) -> str:
    if reason is None:
        return "At least one live validation option candidate passed filters."
    return {
        "NO_EXPIRIES": "Yahoo returned no option expiries for this ticker.",
        "NO_EXPIRY_IN_DTE_RANGE": "Yahoo expiries exist, but none are between 7 and 45 DTE.",
        "NO_CALLS_FROM_PROVIDER": "Yahoo returned no usable call chain data.",
        "ALL_CALLS_FAILED_STRIKE_FILTER": "Calls existed, but none were inside the live strike window.",
        "ALL_CALLS_FAILED_QUOTE_FILTER": "Calls existed, but none had usable bid/ask or lastPrice fallback quotes.",
        "ALL_CALLS_FAILED_GREEKS_FILTER": "Calls existed, but none passed IV, Greek, spread, or open-interest filters.",
    }.get(reason, "No valid option contract found.")


def _score_live_option_candidates(candidates: list[dict]) -> list[OptionSignal]:
    if not candidates:
        return []
    theta_values = [_theta_efficiency(candidate.get("delta"), candidate.get("theta")) for candidate in candidates]
    scored = []
    for candidate, theta_efficiency in zip(candidates, theta_values):
        momentum_score = _clamp_score(candidate.get("underlying_momentum_score"), 0.5)
        liquidity_score = _liquidity_score(candidate.get("bid"), candidate.get("ask"), candidate.get("mid"), candidate.get("open_interest"))
        theta_efficiency_score = _normalize_value(theta_efficiency, theta_values)
        delta_score = _delta_score(candidate.get("delta"))
        iv_score = _iv_score(candidate.get("implied_vol"))
        dte_score = _dte_score(candidate.get("dte"))
        score_breakdown = _contract_score_breakdown(
            momentum_score=momentum_score,
            liquidity_score=liquidity_score,
            theta_efficiency_score=theta_efficiency_score,
            delta_score=delta_score,
            iv_score=iv_score,
            dte_score=dte_score,
        )
        total_score = sum(score_breakdown.values())
        scored.append(
            OptionSignal(
                ticker=candidate["ticker"],
                contract_symbol=candidate["contract_symbol"],
                expiry=candidate["expiry"],
                strike=candidate["strike"],
                right=candidate["right"],
                bid=candidate["bid"],
                ask=candidate["ask"],
                mid=candidate["mid"],
                delta=candidate["delta"],
                gamma=candidate["gamma"],
                theta=candidate["theta"],
                vega=candidate["vega"],
                implied_vol=candidate["implied_vol"],
                open_interest=candidate["open_interest"],
                dte=candidate["dte"],
                total_score=float(total_score),
                quote_quality=candidate["quote_quality"],
                score_breakdown=score_breakdown,
                score_details=_contract_score_details(score_breakdown, candidate["quote_quality"]),
                momentum_score=momentum_score,
                liquidity_score=liquidity_score,
                theta_efficiency_score=theta_efficiency_score,
                delta_score=delta_score,
                iv_score=iv_score,
                dte_score=dte_score,
            )
        )
    return scored


def _contract_score_breakdown(
    momentum_score: float,
    liquidity_score: float,
    theta_efficiency_score: float,
    delta_score: float,
    iv_score: float,
    dte_score: float,
) -> dict[str, float]:
    return {
        "liquidity": float(liquidity_score * 25),
        "momentum": float(momentum_score * 20),
        "theta_efficiency": float(theta_efficiency_score * 20),
        "delta": float(delta_score * 15),
        "iv": float(iv_score * 10),
        "dte": float(dte_score * 10),
    }


def _contract_score_details(score_breakdown: dict[str, float], quote_quality: str) -> str:
    strongest = max(score_breakdown, key=lambda key: score_breakdown[key])
    weakest = min(score_breakdown, key=lambda key: score_breakdown[key])
    quote_note = "Fallback quote; validate bid/ask carefully." if quote_quality == "fallback" else "Live Yahoo quote."
    return f"Strongest component: {strongest}. Weakest component: {weakest}. {quote_note}"


def get_underlying_momentum_score(stock: StockSignal | str) -> float:
    if isinstance(stock, StockSignal):
        return _clamp_score(stock.momentum_score, 0.5)
    return 0.5


def _delta_score(delta: float | None) -> float:
    if delta is None:
        return 0.5
    if 0.55 <= delta <= 0.65:
        return 1.0
    if 0.50 <= delta < 0.55 or 0.65 < delta <= 0.75:
        return 0.75
    return 0.35


def _theta_efficiency(delta: float | None, theta: float | None) -> float:
    if delta is None or theta is None or abs(theta) <= 0:
        return 0.5
    return max(0.0, float(delta) / abs(float(theta)))


def _iv_score(implied_vol: float | None) -> float:
    if implied_vol is None or implied_vol <= 0:
        return 0.5
    return max(0.0, min(1.0, 1 - ((implied_vol - 0.20) / 1.00)))


def _liquidity_score(bid: float | None, ask: float | None, mid: float | None, open_interest: int | None) -> float:
    if bid is None or ask is None or mid is None or mid <= 0:
        return 0.5
    spread_pct = (ask - bid) / mid
    oi = float(open_interest or 0)
    oi_score = min(oi / 1000, 1.0)
    if oi < 100:
        oi_score *= 0.50
    if bid <= 0 or ask <= 0:
        spread_score = 0.25
    elif spread_pct <= 0.05:
        spread_score = 1.0
    elif spread_pct <= 0.12:
        spread_score = 0.75
    elif spread_pct <= 0.20:
        spread_score = 0.45
    else:
        spread_score = 0.20
    return max(0.0, min(1.0, 0.55 * oi_score + 0.45 * spread_score))


def _dte_score(dte: int | None) -> float:
    if dte is None:
        return 0.5
    if 21 <= dte <= 45:
        return 1.0
    if 14 <= dte < 21 or 45 < dte <= 60:
        return 0.7
    return 0.4


def _normalize_value(value: float | None, values: list[float]) -> float:
    if value is None:
        return 0.5
    clean = [float(item) for item in values if item is not None]
    if not clean:
        return 0.5
    low = min(clean)
    high = max(clean)
    if high == low:
        return 0.5 if value == 0.5 else 1.0
    return max(0.0, min(1.0, (float(value) - low) / (high - low)))


def _clamp_score(value, fallback: float = 0.5) -> float:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return fallback


def _print_option_diagnostic(diagnostic: OptionDiagnostic) -> None:
    print(f"[{diagnostic.ticker}] live option diagnostics")
    print(f"  last_price: {diagnostic.last_price:.2f}")
    print(f"  available option expiries: {diagnostic.available_expiries}")
    print(f"  selected expiries after DTE filter: {diagnostic.selected_expiries}")
    print(f"  calls before filters: {diagnostic.calls_before_filters}")
    print(f"  after strike window filter: {diagnostic.after_strike_filter}")
    print(f"  after bid/ask filter: {diagnostic.after_quote_filter}")
    print(f"  after IV filter: {diagnostic.after_iv_filter}")
    print(f"  after delta/theta filter: {diagnostic.after_greeks_filter}")
    if diagnostic.failure_reason:
        print(f"  failure_reason: {diagnostic.failure_reason}")


def _regime_status(benchmark_data: pd.DataFrame) -> str:
    if benchmark_data.empty or len(benchmark_data) < 50:
        return "unknown"
    close = benchmark_data["close"].dropna()
    sma50 = close.rolling(50).mean().iloc[-1]
    return "risk-on" if float(close.iloc[-1]) > float(sma50) else "risk-off"


def _append_log(event: str, config: dict) -> None:
    path = config.get("live", {}).get("dashboard_log_path", "output/live_dashboard_log.jsonl")
    ensure_parent_dir(path)
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps({"event": event, "timestamp": pd.Timestamp.now().isoformat()}) + "\n")
