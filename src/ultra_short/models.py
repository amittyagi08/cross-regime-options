from __future__ import annotations

from dataclasses import asdict, dataclass, field


ULTRA_SHORT_STATES = [
    "CALL_WATCH",
    "CALL_SETUP_FORMING",
    "CALL_TRIGGERED",
    "PUT_WATCH",
    "PUT_SETUP_FORMING",
    "PUT_TRIGGERED",
    "CHOP_NO_TRADE",
    "EXTENDED_DO_NOT_CHASE",
]


@dataclass(frozen=True)
class UltraShortMarketBias:
    mode: str
    call_readiness: float
    put_readiness: float
    market_bias_score: float
    notes: str


@dataclass(frozen=True)
class IntradaySectorRank:
    rank: int
    sector: str
    etf: str
    today_return: float
    trend_60m: str
    vwap_state: str
    relative_strength: float
    ultra_short_bias: str
    intraday_sector_score: float


@dataclass(frozen=True)
class UltraShortSetupCandidate:
    ticker: str
    direction: str
    setup_state: str
    market_bias_score: float
    intraday_sector_score: float
    ticker_vwap_setup_score: float
    entry_trigger_score: float
    option_contract_quality_score: float
    swing_quality_score: float
    ultra_short_score: float
    contract_symbol: str | None = None
    expiry: str | None = None
    strike: float | None = None
    right: str | None = None
    bid: float | None = None
    ask: float | None = None
    suggested_premium: float | None = None
    delta: float | None = None
    theta: float | None = None
    iv: float | None = None
    open_interest: int | None = None
    dte: int | None = None
    spread_pct: float | None = None
    entry_trigger: str = ""
    invalidation_rule: str = ""
    stop_rule: str = ""
    time_rule: str = ""
    status: str = "REVIEW_REQUIRED"
    review_notes: str = ""
    rejection_reason: str = ""


@dataclass(frozen=True)
class UltraShortSnapshot:
    as_of: str
    status: str
    mode: str
    warning: str
    states: list[str]
    market_bias: UltraShortMarketBias
    intraday_sectors: list[IntradaySectorRank] = field(default_factory=list)
    call_setups: list[UltraShortSetupCandidate] = field(default_factory=list)
    put_setups: list[UltraShortSetupCandidate] = field(default_factory=list)
    active_trades: list[dict] = field(default_factory=list)
    closed_trades: list[dict] = field(default_factory=list)
    recent_marks: list[dict] = field(default_factory=list)
    implementation_phase: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
