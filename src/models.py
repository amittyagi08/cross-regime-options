from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class MomentumSignal:
    ticker: str
    last_price: float
    momentum_score: float
    return_5d: float
    return_10d: float
    volume_ratio: float


@dataclass(frozen=True)
class OptionCandidate:
    ticker: str
    expiry: str
    strike: float
    right: str
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    delta: Optional[float]
    gamma: Optional[float]
    theta: Optional[float]
    vega: Optional[float]
    implied_vol: Optional[float]
    open_interest: Optional[int]
    dte: Optional[int]
    momentum_score: float
    liquidity_score: float
    total_score: float

    def with_scores(self, liquidity_score: float, total_score: float) -> "OptionCandidate":
        return replace(self, liquidity_score=liquidity_score, total_score=total_score)
