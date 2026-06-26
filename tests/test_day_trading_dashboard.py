from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.day_trading.intraday_provider import IntradayProvider
from src.day_trading.models import IntradayBar
from src.day_trading.scoring import score_market_status
from src.day_trading.service import build_day_trading_snapshot


class FakeIntradayProvider(IntradayProvider):
    def get_intraday_bars(self, symbol: str, interval: str = "5m", lookback: str = "1d") -> list[IntradayBar]:
        start = datetime(2026, 6, 24, 9, 30)
        bars = []
        base = 100.0 if symbol != "QQQ" else 200.0
        step = 0.12 if symbol != "QQQ" else 0.18
        for index in range(30):
            day_start = start + timedelta(days=0 if index < 15 else 1)
            timestamp = day_start + timedelta(minutes=5 * (index % 15))
            close = base + (index * step)
            bars.append(
                IntradayBar(
                    symbol=symbol,
                    timestamp=timestamp.isoformat(),
                    open=close - 0.05,
                    high=close + 0.20,
                    low=close - 0.20,
                    close=close,
                    volume=1000 + (index * 25),
                )
            )
        return bars


def test_day_trading_scoring_detects_long_bias():
    bars = FakeIntradayProvider().get_intraday_bars("SPY")

    status = score_market_status("SPY", bars, bars)

    assert status.status in {"LONG_BIAS", "STRONG_LONG"}
    assert status.vwap_state == "ABOVE_VWAP"
    assert status.pivots.pp is not None
    assert status.pivots.opening_range_high is not None


def test_day_trading_snapshot_uses_provider_boundary():
    snapshot = build_day_trading_snapshot(
        {
            "day_trading": {
                "market_symbols": ["SPY", "QQQ"],
                "watchlist": ["MSFT", "NVDA"],
                "max_trades_per_day": 2,
            }
        },
        provider=FakeIntradayProvider(),
    )

    assert snapshot["provider"] == "yahoo"
    assert snapshot["market_status"] in {"LONG_BIAS", "STRONG_LONG"}
    assert len(snapshot["market_rows"]) == 2
    assert snapshot["long_setups"][0]["ticker"] in {"MSFT", "NVDA"}
    assert snapshot["daily_performance"]["max_trades_per_day"] == 2


def test_day_trading_routes_are_separate_screen():
    client = TestClient(
        create_app(
            {
                "live": {"provider": "yahoo", "allow_order_placement": False},
                "day_trading": {"watchlist": ["MSFT"], "market_symbols": ["SPY", "QQQ"]},
            }
        )
    )

    page = client.get("/day-trading")

    assert page.status_code == 200
    assert "Day Trading Dashboard" in page.text
