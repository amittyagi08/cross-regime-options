from __future__ import annotations

from src.live.signal_snapshot import OptionSignal, SectorSignal, StockSignal


def clamp_score(value: float | None, fallback: float = 50.0) -> float:
    if value is None:
        return fallback
    return max(0.0, min(100.0, float(value)))


def ultra_short_market_bias_score(regime_status: str, sectors: list[SectorSignal]) -> tuple[str, float, float, float]:
    selected = [sector for sector in sectors if sector.selected]
    sample = selected or sectors
    if not sample:
        return "NOT_READY", 0.0, 0.0, 0.0

    avg_score = sum(sector.sector_score for sector in sample) / len(sample)
    avg_1w = sum(sector.return_1w for sector in sample) / len(sample)
    trend_bonus = 10.0 if avg_1w > 0 else -10.0 if avg_1w < 0 else 0.0
    regime_bonus = 10.0 if regime_status == "risk-on" else -10.0 if regime_status == "risk-off" else 0.0
    bias_score = clamp_score(avg_score + trend_bonus + regime_bonus)

    call_readiness = bias_score
    put_readiness = clamp_score(100.0 - bias_score + (5.0 if regime_status == "risk-off" else 0.0))
    if call_readiness >= 65:
        mode = "CALL_BIASED"
    elif put_readiness >= 55:
        mode = "PUT_BIASED"
    elif call_readiness >= 50:
        mode = "CALL_WATCH"
    elif put_readiness >= 40:
        mode = "PUT_WATCH"
    else:
        mode = "CHOP_NO_TRADE"
    return mode, round(call_readiness, 2), round(put_readiness, 2), round(bias_score, 2)


def intraday_sector_score(sector: SectorSignal, benchmark_score: float) -> float:
    return clamp_score((sector.sector_score * 0.75) + (sector.return_1w * 1000.0) + ((sector.sector_score - benchmark_score) * 0.10))


def sector_bias(score: float, return_1w: float) -> str:
    if score >= 70 and return_1w >= 0:
        return "CALL_BIASED"
    if score <= 45 or return_1w < -0.01:
        return "PUT_WATCH"
    return "MIXED"


def trend_label(return_1w: float) -> str:
    if return_1w >= 0.015:
        return "UP"
    if return_1w <= -0.015:
        return "DOWN"
    return "FLAT"


def vwap_state_from_score(score: float) -> str:
    if score >= 70:
        return "ABOVE_VWAP_PROXY"
    if score <= 40:
        return "BELOW_VWAP_PROXY"
    return "NEAR_VWAP_PROXY"


def ticker_vwap_setup_score(stock: StockSignal, sector_score: float, direction: str) -> float:
    momentum = clamp_score(stock.momentum_score * 100.0)
    stock_quality = clamp_score(stock.stock_score)
    base = (momentum * 0.55) + (stock_quality * 0.30) + (sector_score * 0.15)
    if direction == "PUT":
        base = 100.0 - base
    return clamp_score(base)


def entry_trigger_score(setup_score: float, market_score: float, direction: str) -> float:
    directional_market = market_score if direction == "CALL" else 100.0 - market_score
    return clamp_score((setup_score * 0.65) + (directional_market * 0.35))


def option_contract_quality_score(option: OptionSignal | None) -> float:
    if option is None:
        return 0.0
    return clamp_score(option.total_score)


def ultra_short_score(
    market_bias_score: float,
    sector_score: float,
    ticker_setup_score: float,
    trigger_score: float,
    contract_quality_score: float,
    swing_quality_score: float,
) -> float:
    return round(
        (market_bias_score * 0.25)
        + (sector_score * 0.20)
        + (ticker_setup_score * 0.25)
        + (trigger_score * 0.15)
        + (contract_quality_score * 0.10)
        + (swing_quality_score * 0.05),
        2,
    )
