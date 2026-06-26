from __future__ import annotations

from datetime import time

import pandas as pd

from src.day_trading.models import DayTradeSignal, IntradayBar, MarketStatus, PivotLevels


def score_market_status(symbol: str, bars_5m: list[IntradayBar], bars_1m: list[IntradayBar] | None = None) -> MarketStatus:
    frame = _bars_frame(bars_5m)
    if frame.empty:
        return MarketStatus(symbol, "MIXED_CHOP", None, None, "NO_DATA", 0.0, "NO_DATA", "NO_DATA", None, 0.0)
    pivots = pivot_levels(bars_5m, bars_1m or bars_5m)
    last_price = float(frame["close"].iloc[-1])
    vwap_series = _vwap_series(frame)
    vwap = float(vwap_series.iloc[-1])
    distance = (last_price / vwap) - 1.0 if vwap > 0 else None
    slope = _slope(vwap_series)
    vwap_state = _vwap_state(distance)
    pivot_position = _pivot_position(last_price, pivots)
    trend = _trend_structure(frame)
    score = _market_score(vwap_state, slope, pivot_position, trend, distance)
    return MarketStatus(
        symbol=symbol,
        status=_market_state(score, distance),
        last_price=round(last_price, 2),
        vwap=round(vwap, 2),
        vwap_state=vwap_state,
        vwap_slope=round(slope, 5),
        pivot_position=pivot_position,
        trend_structure=trend,
        distance_from_vwap=round(distance, 4) if distance is not None else None,
        score=round(score, 2),
        pivots=pivots,
    )


def build_ticker_signal(
    ticker: str,
    bars_5m: list[IntradayBar],
    market_score: float,
    market_status: str,
    direction: str,
    bars_1m: list[IntradayBar] | None = None,
) -> DayTradeSignal:
    status = score_market_status(ticker, bars_5m, bars_1m)
    if status.last_price is None:
        return _empty_signal(ticker, direction)
    vwap_score = _directional_vwap_score(status, direction)
    pivot_score, pivot_label = _directional_pivot_score(status, direction)
    momentum_score = _directional_momentum_score(status, direction)
    volume_score, volume_label = _volume_score(bars_5m)
    directional_market_score = market_score if direction == "LONG" else 100.0 - market_score
    total = (
        directional_market_score * 0.30
        + vwap_score * 0.25
        + pivot_score * 0.20
        + momentum_score * 0.15
        + volume_score * 0.10
    )
    far_from_vwap = status.distance_from_vwap is not None and abs(status.distance_from_vwap) >= 0.012
    state = _signal_state(total, far_from_vwap)
    market_confirmed = _market_confirms(market_status, direction)
    setup = _setup_type(status, direction, pivot_label)
    entry, stop, target = _trade_plan(status, direction, pivot_label)
    return DayTradeSignal(
        ticker=ticker,
        direction=direction,
        setup=setup,
        signal_state=state,
        market_confirmed=market_confirmed,
        vwap_state=status.vwap_state,
        pivot_level=pivot_label,
        day_long_score=round(total if direction == "LONG" else 100.0 - total, 2),
        day_short_score=round(total if direction == "SHORT" else 100.0 - total, 2),
        score=round(total, 2),
        entry_trigger=entry,
        stop=stop,
        target=target,
        action=_action(state, market_confirmed),
        last_price=status.last_price,
        volume_confirmation=volume_label,
    )


def pivot_levels(bars_5m: list[IntradayBar], opening_bars: list[IntradayBar]) -> PivotLevels:
    frame = _bars_frame(bars_5m)
    if frame.empty:
        return PivotLevels()
    previous = _previous_session(frame)
    opening = _opening_range(_bars_frame(opening_bars))
    if previous.empty:
        return PivotLevels(opening_range_high=opening[0], opening_range_low=opening[1])
    high = float(previous["high"].max())
    low = float(previous["low"].min())
    close = float(previous["close"].iloc[-1])
    pp = (high + low + close) / 3.0
    return PivotLevels(
        pp=round(pp, 2),
        r1=round((2 * pp) - low, 2),
        r2=round(pp + (high - low), 2),
        r3=round(high + 2 * (pp - low), 2),
        s1=round((2 * pp) - high, 2),
        s2=round(pp - (high - low), 2),
        s3=round(low - 2 * (high - pp), 2),
        previous_high=round(high, 2),
        previous_low=round(low, 2),
        opening_range_high=opening[0],
        opening_range_low=opening[1],
    )


def _bars_frame(bars: list[IntradayBar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()
    frame = pd.DataFrame([bar.__dict__ for bar in bars])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["timestamp", "close"]).sort_values("timestamp")


def _vwap_series(frame: pd.DataFrame) -> pd.Series:
    typical = (frame["high"].fillna(frame["close"]) + frame["low"].fillna(frame["close"]) + frame["close"]) / 3.0
    volume = frame["volume"].fillna(0.0)
    cumulative_volume = volume.cumsum()
    vwap = (typical * volume).cumsum() / cumulative_volume.replace(0, pd.NA)
    return vwap.ffill().fillna(frame["close"])


def _slope(series: pd.Series, bars: int = 6) -> float:
    if len(series) <= bars:
        return 0.0
    base = float(series.iloc[-1 - bars])
    return (float(series.iloc[-1]) / base) - 1.0 if base > 0 else 0.0


def _vwap_state(distance: float | None) -> str:
    if distance is None:
        return "NO_DATA"
    if distance >= 0.001:
        return "ABOVE_VWAP"
    if distance <= -0.001:
        return "BELOW_VWAP"
    return "NEAR_VWAP"


def _pivot_position(price: float, pivots: PivotLevels) -> str:
    if pivots.pp is None:
        return "NO_PIVOT"
    if pivots.r1 is not None and price >= pivots.r1:
        return "ABOVE_R1"
    if pivots.s1 is not None and price <= pivots.s1:
        return "BELOW_S1"
    if price >= pivots.pp:
        return "ABOVE_PP"
    return "BELOW_PP"


def _trend_structure(frame: pd.DataFrame) -> str:
    if len(frame) < 8:
        return "NO_DATA"
    recent = frame.tail(8)
    highs = recent["high"].tolist()
    lows = recent["low"].tolist()
    higher_high = highs[-1] > max(highs[:4])
    higher_low = min(lows[-4:]) > min(lows[:4])
    lower_high = max(highs[-4:]) < max(highs[:4])
    lower_low = lows[-1] < min(lows[:4])
    if higher_high and higher_low:
        return "HIGHER_HIGH_HIGHER_LOW"
    if lower_high and lower_low:
        return "LOWER_HIGH_LOWER_LOW"
    if higher_high:
        return "HIGHER_HIGH"
    if lower_low:
        return "LOWER_LOW"
    return "RANGE"


def _market_score(vwap_state: str, slope: float, pivot_position: str, trend: str, distance: float | None) -> float:
    score = 50.0
    score += {"ABOVE_VWAP": 18.0, "NEAR_VWAP": 0.0, "BELOW_VWAP": -18.0}.get(vwap_state, 0.0)
    score += 10.0 if slope > 0.0004 else -10.0 if slope < -0.0004 else 0.0
    score += {"ABOVE_R1": 12.0, "ABOVE_PP": 7.0, "BELOW_PP": -7.0, "BELOW_S1": -12.0}.get(pivot_position, 0.0)
    score += {"HIGHER_HIGH_HIGHER_LOW": 10.0, "HIGHER_HIGH": 5.0, "LOWER_HIGH_LOWER_LOW": -10.0, "LOWER_LOW": -5.0}.get(trend, 0.0)
    if distance is not None and abs(distance) >= 0.018:
        score += 4.0 if distance > 0 else -4.0
    return max(0.0, min(100.0, score))


def _market_state(score: float, distance: float | None) -> str:
    if distance is not None and abs(distance) >= 0.025:
        return "EXTENDED_DO_NOT_CHASE"
    if score >= 78:
        return "STRONG_LONG"
    if score >= 58:
        return "LONG_BIAS"
    if score <= 22:
        return "STRONG_SHORT"
    if score <= 42:
        return "SHORT_BIAS"
    return "MIXED_CHOP"


def _previous_session(frame: pd.DataFrame) -> pd.DataFrame:
    latest_date = frame["timestamp"].dt.date.max()
    previous_dates = sorted(date for date in frame["timestamp"].dt.date.unique() if date < latest_date)
    if not previous_dates:
        return pd.DataFrame()
    return frame[frame["timestamp"].dt.date == previous_dates[-1]]


def _opening_range(frame: pd.DataFrame) -> tuple[float | None, float | None]:
    if frame.empty:
        return None, None
    latest_date = frame["timestamp"].dt.date.max()
    today = frame[frame["timestamp"].dt.date == latest_date]
    if today.empty:
        return None, None
    regular = today[today["timestamp"].dt.time >= time(9, 30)]
    opening = (regular if not regular.empty else today).head(30)
    return round(float(opening["high"].max()), 2), round(float(opening["low"].min()), 2)


def _directional_vwap_score(status: MarketStatus, direction: str) -> float:
    positive = status.vwap_state == "ABOVE_VWAP" and status.vwap_slope >= 0
    negative = status.vwap_state == "BELOW_VWAP" and status.vwap_slope <= 0
    if direction == "LONG":
        return 85.0 if positive else 55.0 if status.vwap_state == "NEAR_VWAP" else 25.0
    return 85.0 if negative else 55.0 if status.vwap_state == "NEAR_VWAP" else 25.0


def _directional_pivot_score(status: MarketStatus, direction: str) -> tuple[float, str]:
    label = status.pivot_position
    long_score = {"ABOVE_R1": 90.0, "ABOVE_PP": 75.0, "BELOW_PP": 35.0, "BELOW_S1": 20.0}.get(label, 50.0)
    return (long_score, label) if direction == "LONG" else (100.0 - long_score, label)


def _directional_momentum_score(status: MarketStatus, direction: str) -> float:
    bullish = status.trend_structure in {"HIGHER_HIGH_HIGHER_LOW", "HIGHER_HIGH"}
    bearish = status.trend_structure in {"LOWER_HIGH_LOWER_LOW", "LOWER_LOW"}
    if direction == "LONG":
        return 85.0 if bullish else 35.0 if bearish else 55.0
    return 85.0 if bearish else 35.0 if bullish else 55.0


def _volume_score(bars: list[IntradayBar]) -> tuple[float, str]:
    frame = _bars_frame(bars)
    if len(frame) < 8:
        return 50.0, "NO_DATA"
    latest = float(frame["volume"].tail(3).mean())
    baseline = float(frame["volume"].iloc[:-3].tail(20).mean())
    if baseline <= 0:
        return 50.0, "NO_DATA"
    ratio = latest / baseline
    if ratio >= 1.25:
        return 85.0, "CONFIRMED"
    if ratio >= 0.85:
        return 60.0, "NORMAL"
    return 35.0, "LIGHT"


def _signal_state(score: float, far_from_vwap: bool) -> str:
    if far_from_vwap and score >= 65:
        return "EXTENDED_DO_NOT_CHASE"
    if score >= 75:
        return "TRIGGERED"
    if score >= 60:
        return "SETUP_FORMING"
    if score >= 42:
        return "WATCH"
    return "INVALIDATED"


def _market_confirms(market_status: str, direction: str) -> bool:
    if direction == "LONG":
        return market_status in {"STRONG_LONG", "LONG_BIAS", "RANGE_FADE"}
    return market_status in {"STRONG_SHORT", "SHORT_BIAS", "RANGE_FADE"}


def _setup_type(status: MarketStatus, direction: str, pivot_label: str) -> str:
    if direction == "LONG":
        if pivot_label == "ABOVE_R1":
            return "R1_BREAKOUT_LONG"
        if status.vwap_state in {"ABOVE_VWAP", "NEAR_VWAP"}:
            return "VWAP_RECLAIM_LONG"
        return "PIVOT_RECLAIM_LONG"
    if pivot_label == "BELOW_S1":
        return "S1_BREAKDOWN_SHORT"
    if status.vwap_state in {"BELOW_VWAP", "NEAR_VWAP"}:
        return "VWAP_REJECTION_SHORT"
    return "PIVOT_LOSS_SHORT"


def _trade_plan(status: MarketStatus, direction: str, pivot_label: str) -> tuple[str, str, str]:
    price = status.last_price or 0.0
    if direction == "LONG":
        entry = f"Break and hold above {max(price, status.vwap or price):.2f}"
        stop = f"VWAP/trigger candle loss near {(status.vwap or price):.2f}"
        target = _first_available(status.pivots.r1, status.pivots.r2, status.pivots.previous_high, fallback=price * 1.01)
    else:
        entry = f"Reject below {min(price, status.vwap or price):.2f}"
        stop = f"VWAP/trigger candle reclaim near {(status.vwap or price):.2f}"
        target = _first_available(status.pivots.s1, status.pivots.s2, status.pivots.previous_low, fallback=price * 0.99)
    return entry, stop, f"{target:.2f}"


def _first_available(*values: float | None, fallback: float) -> float:
    for value in values:
        if value is not None:
            return value
    return fallback


def _action(state: str, market_confirmed: bool) -> str:
    if state == "TRIGGERED" and market_confirmed:
        return "Manual Review"
    if state == "EXTENDED_DO_NOT_CHASE":
        return "Do Not Chase"
    if state == "INVALIDATED":
        return "No Trade"
    return "Watch"


def _empty_signal(ticker: str, direction: str) -> DayTradeSignal:
    return DayTradeSignal(
        ticker=ticker,
        direction=direction,
        setup="NO_DATA",
        signal_state="WATCH",
        market_confirmed=False,
        vwap_state="NO_DATA",
        pivot_level="NO_DATA",
        day_long_score=0.0,
        day_short_score=0.0,
        score=0.0,
        entry_trigger="No intraday bars available.",
        stop="-",
        target="-",
        action="Watch",
        last_price=None,
        volume_confirmation="NO_DATA",
    )
