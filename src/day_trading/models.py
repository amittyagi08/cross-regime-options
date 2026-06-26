from __future__ import annotations

from dataclasses import asdict, dataclass, field


MARKET_STATUS_STATES = [
    "STRONG_LONG",
    "LONG_BIAS",
    "SHORT_BIAS",
    "STRONG_SHORT",
    "MIXED_CHOP",
    "RANGE_FADE",
    "EXTENDED_DO_NOT_CHASE",
    "REVERSAL_WATCH",
]

SIGNAL_STATES = [
    "WATCH",
    "SETUP_FORMING",
    "TRIGGERED",
    "EXTENDED_DO_NOT_CHASE",
    "INVALIDATED",
]


@dataclass(frozen=True)
class IntradayBar:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class PivotLevels:
    pp: float | None = None
    r1: float | None = None
    r2: float | None = None
    r3: float | None = None
    s1: float | None = None
    s2: float | None = None
    s3: float | None = None
    previous_high: float | None = None
    previous_low: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None


@dataclass(frozen=True)
class MarketStatus:
    symbol: str
    status: str
    last_price: float | None
    vwap: float | None
    vwap_state: str
    vwap_slope: float
    pivot_position: str
    trend_structure: str
    distance_from_vwap: float | None
    score: float
    pivots: PivotLevels = field(default_factory=PivotLevels)


@dataclass(frozen=True)
class DayTradeSignal:
    ticker: str
    direction: str
    setup: str
    signal_state: str
    market_confirmed: bool
    vwap_state: str
    pivot_level: str
    day_long_score: float
    day_short_score: float
    score: float
    entry_trigger: str
    stop: str
    target: str
    action: str
    last_price: float | None
    volume_confirmation: str


@dataclass(frozen=True)
class DayTradingSnapshot:
    as_of: str
    provider: str
    mode: str
    warning: str
    market_status: str
    market_score: float
    states: list[str]
    market_rows: list[MarketStatus] = field(default_factory=list)
    pivot_map: list[dict] = field(default_factory=list)
    long_setups: list[DayTradeSignal] = field(default_factory=list)
    short_setups: list[DayTradeSignal] = field(default_factory=list)
    active_trades: list[dict] = field(default_factory=list)
    closed_trades: list[dict] = field(default_factory=list)
    daily_performance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
