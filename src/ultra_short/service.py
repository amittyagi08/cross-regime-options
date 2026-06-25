from __future__ import annotations

from datetime import datetime

import pandas as pd
import yfinance as yf

from src.black_scholes import calculate_call_greeks
from src.live.signal_service import load_latest_snapshot
from src.live.signal_snapshot import LiveSignalSnapshot, OptionSignal, SectorSignal, StockSignal
from src.utils import calculate_dte
from src.ultra_short.models import (
    ULTRA_SHORT_STATES,
    IntradaySectorRank,
    UltraShortMarketBias,
    UltraShortSetupCandidate,
    UltraShortSnapshot,
)
from src.ultra_short.scoring import (
    entry_trigger_score,
    intraday_sector_score,
    option_contract_quality_score,
    sector_bias,
    ticker_vwap_setup_score,
    trend_label,
    ultra_short_market_bias_score,
    ultra_short_score,
    vwap_state_from_score,
)


def build_ultra_short_snapshot(
    config: dict | None = None,
    live_snapshot: LiveSignalSnapshot | None = None,
) -> dict:
    """Build the ultra-short snapshot payload from the latest live validation snapshot."""
    config = config or {}
    live_snapshot = live_snapshot or load_latest_snapshot(config)
    if live_snapshot is None:
        return _empty_snapshot(
            status="waiting_for_live_snapshot",
            notes="Run a live snapshot first so the lab can reuse sector, universe, and option-chain data.",
        ).to_dict()

    market_bias = _market_bias(live_snapshot)
    intraday_sectors = _intraday_sector_ranks(live_snapshot.sectors)
    call_setups = _call_setup_candidates(live_snapshot, market_bias, intraday_sectors, config)
    put_setups = _put_setup_candidates(live_snapshot, market_bias, intraday_sectors, config)

    snapshot = UltraShortSnapshot(
        as_of=live_snapshot.as_of,
        status="phase_5_live_snapshot",
        mode="manual_review_only",
        warning=(
            "Ultra-Short Trade Lab reuses the latest live validation snapshot. "
            "No live orders or auto-ordering. Validate all quotes and intraday triggers on platform."
        ),
        states=ULTRA_SHORT_STATES,
        market_bias=market_bias,
        intraday_sectors=intraday_sectors,
        call_setups=call_setups,
        put_setups=put_setups,
        active_trades=[],
        closed_trades=[],
        recent_marks=[],
        implementation_phase={
            "current": "Phase 5 - Analytics and Exports",
            "next": "Intraday VWAP Inputs and Put Contract Refinement",
        },
    )
    return snapshot.to_dict()


def _empty_snapshot(status: str, notes: str) -> UltraShortSnapshot:
    return UltraShortSnapshot(
        as_of=datetime.now().astimezone().isoformat(timespec="seconds"),
        status=status,
        mode="manual_review_only",
        warning="Ultra-Short Trade Lab is a separate research portal. No live orders or auto-ordering.",
        states=ULTRA_SHORT_STATES,
        market_bias=UltraShortMarketBias(
            mode="NOT_READY",
            call_readiness=0.0,
            put_readiness=0.0,
            market_bias_score=0.0,
            notes=notes,
        ),
        implementation_phase={
            "current": "Phase 5 - Analytics and Exports",
            "next": "Intraday VWAP Inputs and Put Contract Refinement",
        },
    )


def _market_bias(snapshot: LiveSignalSnapshot) -> UltraShortMarketBias:
    mode, call_readiness, put_readiness, bias_score = ultra_short_market_bias_score(
        snapshot.regime_status,
        snapshot.sectors,
    )
    notes = (
        f"Derived from latest live snapshot regime={snapshot.regime_status} and sector strength. "
        "VWAP and 60m labels remain proxy states until true intraday bars are connected."
    )
    return UltraShortMarketBias(
        mode=mode,
        call_readiness=call_readiness,
        put_readiness=put_readiness,
        market_bias_score=bias_score,
        notes=notes,
    )


def _intraday_sector_ranks(sectors: list[SectorSignal]) -> list[IntradaySectorRank]:
    if not sectors:
        return []
    benchmark_score = sum(sector.sector_score for sector in sectors) / len(sectors)
    rows = []
    for sector in sectors:
        score = intraday_sector_score(sector, benchmark_score)
        rows.append(
            IntradaySectorRank(
                rank=0,
                sector=sector.sector,
                etf=sector.etf,
                today_return=round(sector.return_1w / 5.0, 4),
                trend_60m=trend_label(sector.return_1w),
                vwap_state=vwap_state_from_score(score),
                relative_strength=round((sector.sector_score - benchmark_score) / 100.0, 4),
                ultra_short_bias=sector_bias(score, sector.return_1w),
                intraday_sector_score=round(score, 2),
            )
        )
    rows = sorted(rows, key=lambda row: row.intraday_sector_score, reverse=True)
    return [
        IntradaySectorRank(
            rank=index,
            sector=row.sector,
            etf=row.etf,
            today_return=row.today_return,
            trend_60m=row.trend_60m,
            vwap_state=row.vwap_state,
            relative_strength=row.relative_strength,
            ultra_short_bias=row.ultra_short_bias,
            intraday_sector_score=row.intraday_sector_score,
        )
        for index, row in enumerate(rows, start=1)
    ]


def _call_setup_candidates(
    snapshot: LiveSignalSnapshot,
    market_bias: UltraShortMarketBias,
    sectors: list[IntradaySectorRank],
    config: dict,
) -> list[UltraShortSetupCandidate]:
    max_candidates = int(config.get("ultra_short", {}).get("max_call_setups", 8))
    stocks_by_ticker = {stock.ticker: stock for stock in snapshot.universe}
    sector_scores = {sector.sector: sector.intraday_sector_score for sector in sectors}
    best_options = _best_options_by_ticker(snapshot.options, right="C")
    candidates = []
    for ticker, option in best_options.items():
        stock = stocks_by_ticker.get(ticker)
        if stock is None:
            continue
        sector_score = sector_scores.get(stock.sector, 50.0)
        candidates.append(_setup_candidate(stock, option, "CALL", market_bias, sector_score))
    return sorted(candidates, key=lambda candidate: candidate.ultra_short_score, reverse=True)[:max_candidates]


def _put_setup_candidates(
    snapshot: LiveSignalSnapshot,
    market_bias: UltraShortMarketBias,
    sectors: list[IntradaySectorRank],
    config: dict,
) -> list[UltraShortSetupCandidate]:
    max_candidates = int(config.get("ultra_short", {}).get("max_put_setups", 8))
    sector_scores = {sector.sector: sector.intraday_sector_score for sector in sectors}
    candidates: list[UltraShortSetupCandidate] = []
    for stock in snapshot.universe:
        sector_score = sector_scores.get(stock.sector, 50.0)
        setup_score = ticker_vwap_setup_score(stock, sector_score, "PUT")
        if market_bias.put_readiness < 25 and setup_score < 45:
            continue
        candidates.append(_setup_candidate(stock, None, "PUT", market_bias, sector_score))
    candidates = sorted(candidates, key=lambda candidate: candidate.ultra_short_score, reverse=True)[:max_candidates]
    return [
        _with_live_put_contract(candidate, snapshot, market_bias, sector_scores, config)
        for candidate in candidates
    ]


def _with_live_put_contract(
    candidate: UltraShortSetupCandidate,
    snapshot: LiveSignalSnapshot,
    market_bias: UltraShortMarketBias,
    sector_scores: dict[str, float],
    config: dict,
) -> UltraShortSetupCandidate:
    stock_by_ticker = {stock.ticker: stock for stock in snapshot.universe}
    stock = stock_by_ticker.get(candidate.ticker)
    if stock is None:
        return candidate
    option = _best_live_put_option(stock, config)
    if option is None:
        return candidate
    return _setup_candidate(stock, option, "PUT", market_bias, sector_scores.get(stock.sector, 50.0))


def _setup_candidate(
    stock: StockSignal,
    option: OptionSignal | None,
    direction: str,
    market_bias: UltraShortMarketBias,
    sector_score: float,
) -> UltraShortSetupCandidate:
    market_score = market_bias.market_bias_score if direction == "CALL" else 100.0 - market_bias.market_bias_score
    ticker_score = ticker_vwap_setup_score(stock, sector_score, direction)
    trigger_score = entry_trigger_score(ticker_score, market_bias.market_bias_score, direction)
    contract_score = option_contract_quality_score(option)
    swing_score = stock.stock_score
    total_score = ultra_short_score(market_score, sector_score, ticker_score, trigger_score, contract_score, swing_score)
    state = _setup_state(direction, total_score, trigger_score, market_bias)
    if direction == "PUT" and state == "CHOP_NO_TRADE" and ticker_score >= 55:
        state = "PUT_WATCH"
    spread_pct = _spread_pct(option)
    return UltraShortSetupCandidate(
        ticker=stock.ticker,
        direction=direction,
        setup_state=state,
        market_bias_score=round(market_score, 2),
        intraday_sector_score=round(sector_score, 2),
        ticker_vwap_setup_score=round(ticker_score, 2),
        entry_trigger_score=round(trigger_score, 2),
        option_contract_quality_score=round(contract_score, 2),
        swing_quality_score=round(swing_score, 2),
        ultra_short_score=total_score,
        contract_symbol=option.contract_symbol if option else None,
        expiry=option.expiry if option else None,
        strike=option.strike if option else None,
        right=option.right if option else "P",
        bid=option.bid if option else None,
        ask=option.ask if option else None,
        suggested_premium=option.mid if option else None,
        delta=option.delta if option else None,
        theta=option.theta if option else None,
        iv=option.implied_vol if option else None,
        open_interest=option.open_interest if option else None,
        dte=option.dte if option else None,
        spread_pct=spread_pct,
        entry_trigger=_entry_trigger(direction, state),
        invalidation_rule=_invalidation_rule(direction),
        stop_rule=_stop_rule(),
        time_rule=_time_rule(),
        rejection_reason="" if option or direction == "PUT" else "No live contract available.",
    )


def _best_options_by_ticker(options: list[OptionSignal], right: str) -> dict[str, OptionSignal]:
    output: dict[str, OptionSignal] = {}
    for option in sorted(options, key=lambda item: item.total_score, reverse=True):
        if option.right != right:
            continue
        output.setdefault(option.ticker, option)
    return output


def _best_live_put_option(stock: StockSignal, config: dict) -> OptionSignal | None:
    if not bool(config.get("ultra_short", {}).get("fetch_put_contracts", True)):
        return None
    filters = _ultra_short_option_filters(config)
    try:
        yahoo_stock = yf.Ticker(stock.ticker)
        expiries = [
            expiry
            for expiry in list(yahoo_stock.options or [])
            if filters["min_dte"] <= _dte_from_yahoo_expiry(expiry) <= filters["max_dte"]
        ]
        raw_candidates = []
        for expiry in expiries[: int(config.get("ultra_short", {}).get("max_put_expiries", 4))]:
            chain = yahoo_stock.option_chain(expiry)
            puts = _normalize_yahoo_options(chain.puts)
            if puts.empty:
                continue
            strike_filtered = _filter_put_strike_window(puts, stock.last_price, filters["strike_window_pct"])
            quote_filtered = [_with_live_quote(row) for row in strike_filtered.to_dict("records")]
            quote_filtered = [row for row in quote_filtered if row is not None]
            for row in quote_filtered:
                option = _build_live_put_option(stock, expiry, row, filters, config)
                if option is not None:
                    raw_candidates.append(option)
        scored = _score_put_options(raw_candidates, stock)
        return scored[0] if scored else None
    except Exception as exc:
        print(f"[{stock.ticker}] Yahoo put diagnostic error: {exc}")
        return None


def _ultra_short_option_filters(config: dict) -> dict:
    live_options = config.get("live_options", {})
    ultra_short = config.get("ultra_short", {})
    return {
        "min_dte": int(ultra_short.get("min_dte", live_options.get("min_dte", 7))),
        "max_dte": int(ultra_short.get("max_dte", live_options.get("max_dte", 30))),
        "min_delta": float(ultra_short.get("min_delta", live_options.get("min_delta", 0.45))),
        "max_delta": float(ultra_short.get("max_delta", live_options.get("max_delta", 0.75))),
        "max_bid_ask_spread_pct": float(
            ultra_short.get("max_bid_ask_spread_pct", live_options.get("max_bid_ask_spread_pct", 0.20))
        ),
        "min_open_interest": int(ultra_short.get("min_open_interest", live_options.get("min_open_interest", 0))),
        "strike_window_pct": float(ultra_short.get("strike_window_pct", live_options.get("strike_window_pct", 0.10))),
    }


def _normalize_yahoo_options(options: pd.DataFrame) -> pd.DataFrame:
    required = ["contractSymbol", "strike", "bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility"]
    if options is None or options.empty:
        return pd.DataFrame(columns=required)
    frame = options.copy()
    for column in required:
        if column not in frame.columns:
            frame[column] = None
    return frame[required]


def _filter_put_strike_window(puts: pd.DataFrame, last_price: float, strike_window_pct: float) -> pd.DataFrame:
    min_strike = last_price * (1 - strike_window_pct)
    max_strike = last_price * (1 + strike_window_pct)
    strikes = pd.to_numeric(puts["strike"], errors="coerce")
    return puts[(strikes >= min_strike) & (strikes <= max_strike)].copy()


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


def _build_live_put_option(
    stock: StockSignal,
    yahoo_expiry: str,
    row: dict,
    filters: dict,
    config: dict,
) -> OptionSignal | None:
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
    if greeks is None:
        return None
    put_delta = greeks.delta - 1.0
    abs_delta = abs(put_delta)
    bid = float(row["bid"])
    ask = float(row["ask"])
    mid = float(row["mid"])
    spread_pct = (ask - bid) / mid if mid > 0 else 1.0
    open_interest = _safe_int(row.get("openInterest")) or 0
    if not (filters["min_delta"] <= abs_delta <= filters["max_delta"]):
        return None
    if spread_pct > filters["max_bid_ask_spread_pct"]:
        return None
    if open_interest < filters["min_open_interest"]:
        return None
    return OptionSignal(
        ticker=stock.ticker,
        contract_symbol=str(row.get("contractSymbol") or f"{stock.ticker} {ib_expiry} {strike:g}P"),
        expiry=ib_expiry,
        strike=strike,
        right="P",
        bid=bid,
        ask=ask,
        mid=mid,
        delta=put_delta,
        gamma=greeks.gamma,
        theta=greeks.theta,
        vega=greeks.vega,
        implied_vol=implied_vol,
        open_interest=open_interest,
        dte=dte,
        total_score=0.0,
        quote_quality=str(row.get("quote_quality", "live")),
    )


def _score_put_options(options: list[OptionSignal], stock: StockSignal) -> list[OptionSignal]:
    scored = []
    for option in options:
        liquidity = _liquidity_score(option.bid, option.ask, option.mid, option.open_interest)
        delta = _put_delta_score(option.delta)
        dte = _put_dte_score(option.dte)
        iv = _iv_score(option.implied_vol)
        momentum = max(0.0, min(1.0, 1.0 - float(stock.momentum_score)))
        total = (liquidity * 30.0) + (delta * 25.0) + (dte * 20.0) + (iv * 10.0) + (momentum * 15.0)
        scored.append(
            OptionSignal(
                ticker=option.ticker,
                contract_symbol=option.contract_symbol,
                expiry=option.expiry,
                strike=option.strike,
                right=option.right,
                bid=option.bid,
                ask=option.ask,
                mid=option.mid,
                delta=option.delta,
                gamma=option.gamma,
                theta=option.theta,
                vega=option.vega,
                implied_vol=option.implied_vol,
                open_interest=option.open_interest,
                dte=option.dte,
                total_score=round(total, 2),
                quote_quality=option.quote_quality,
                liquidity_score=liquidity,
                delta_score=delta,
                iv_score=iv,
                dte_score=dte,
                momentum_score=momentum,
            )
        )
    return sorted(scored, key=lambda option: option.total_score, reverse=True)


def _dte_from_yahoo_expiry(expiry: str) -> int:
    return (datetime.strptime(expiry, "%Y-%m-%d").date() - datetime.now().date()).days


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


def _liquidity_score(bid: float | None, ask: float | None, mid: float | None, open_interest: int | None) -> float:
    if bid is None or ask is None or mid is None or mid <= 0:
        return 0.5
    spread_pct = (ask - bid) / mid
    oi_score = min(float(open_interest or 0) / 1000.0, 1.0)
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


def _put_delta_score(delta: float | None) -> float:
    if delta is None:
        return 0.5
    abs_delta = abs(float(delta))
    if 0.55 <= abs_delta <= 0.65:
        return 1.0
    if 0.45 <= abs_delta < 0.55 or 0.65 < abs_delta <= 0.75:
        return 0.75
    return 0.35


def _put_dte_score(dte: int | None) -> float:
    if dte is None:
        return 0.5
    if 7 <= dte <= 30:
        return 1.0
    if 31 <= dte <= 45:
        return 0.7
    return 0.4


def _iv_score(implied_vol: float | None) -> float:
    if implied_vol is None or implied_vol <= 0:
        return 0.5
    return max(0.0, min(1.0, 1 - ((implied_vol - 0.20) / 1.00)))


def _setup_state(
    direction: str,
    total_score: float,
    trigger_score: float,
    market_bias: UltraShortMarketBias,
) -> str:
    readiness = market_bias.call_readiness if direction == "CALL" else market_bias.put_readiness
    if total_score >= 72 and trigger_score >= 70 and readiness >= 55:
        return f"{direction}_TRIGGERED"
    if total_score >= 58 and readiness >= 40:
        return f"{direction}_SETUP_FORMING"
    if total_score >= 40 or readiness >= 25:
        return f"{direction}_WATCH"
    return "CHOP_NO_TRADE"


def _entry_trigger(direction: str, state: str) -> str:
    if state.endswith("TRIGGERED"):
        return "Manual review: confirm VWAP reclaim/breakout." if direction == "CALL" else "Manual review: confirm VWAP rejection/breakdown."
    if state.endswith("SETUP_FORMING"):
        return "Wait for VWAP reclaim or higher-low confirmation." if direction == "CALL" else "Wait for failed bounce or lower-high confirmation."
    if state.endswith("WATCH"):
        return "Watch only; no entry until intraday confirmation."
    return "No trade in chop."


def _invalidation_rule(direction: str) -> str:
    if direction == "CALL":
        return "Invalidate on VWAP loss, failed breakout, or market mode flip against calls."
    return "Invalidate on VWAP reclaim, failed breakdown, or market mode flip against puts."


def _stop_rule() -> str:
    return "Protect after +10%, breakeven after +15%, trail or partial after +20% to +30%."


def _time_rule() -> str:
    return "Exit before end of session unless explicitly marked as a 1-2 day hold."


def _spread_pct(option: OptionSignal | None) -> float | None:
    if option is None or option.bid is None or option.ask is None or option.mid is None or option.mid <= 0:
        return None
    return round((option.ask - option.bid) / option.mid, 4)
