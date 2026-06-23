from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SectorSignal:
    as_of: str
    sector: str
    etf: str
    sector_score: float
    sector_rank: int
    selected: bool
    return_1w: float
    return_1m: float
    return_3m: float


@dataclass(frozen=True)
class StockSignal:
    ticker: str
    sector: str
    stock_score: float
    stock_rank: int
    selected: bool
    last_price: float
    momentum_score: float


@dataclass(frozen=True)
class OptionSignal:
    ticker: str
    contract_symbol: str
    expiry: str
    strike: float
    right: str
    bid: float | None
    ask: float | None
    mid: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    implied_vol: float | None
    open_interest: int | None
    dte: int | None
    total_score: float
    quote_quality: str = "live"
    score_breakdown: dict[str, float] = field(default_factory=dict)
    score_details: str = ""
    momentum_score: float = 0.5
    liquidity_score: float = 0.5
    theta_efficiency_score: float = 0.5
    delta_score: float = 0.5
    iv_score: float = 0.5
    dte_score: float = 0.5


@dataclass(frozen=True)
class OptionDiagnostic:
    ticker: str
    last_price: float
    available_expiries: list[str]
    selected_expiries: list[str]
    calls_before_filters: int
    after_strike_filter: int
    after_quote_filter: int
    after_iv_filter: int
    after_greeks_filter: int
    failure_reason: str | None
    notes: str


@dataclass(frozen=True)
class RiskDecision:
    ticker: str
    allowed: bool
    reason_codes: list[str]
    position_size_multiplier: float
    notes: str


@dataclass(frozen=True)
class LiveSignalSnapshot:
    as_of: str
    provider: str
    market_status: str
    regime_status: str
    sectors: list[SectorSignal] = field(default_factory=list)
    universe: list[StockSignal] = field(default_factory=list)
    options: list[OptionSignal] = field(default_factory=list)
    option_diagnostics: list[OptionDiagnostic] = field(default_factory=list)
    risk: list[RiskDecision] = field(default_factory=list)
    warning: str = (
        "Data provider: Yahoo. Data may be delayed or incomplete. "
        "Validate on trading platform before any trade."
    )

    def to_dict(self) -> dict:
        return asdict(self)
