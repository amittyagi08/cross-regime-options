from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.live.signal_snapshot import LiveSignalSnapshot, OptionSignal, RiskDecision, SectorSignal, StockSignal
from src.recommendation_logging import (
    get_recommendation,
    list_recommendations,
    log_snapshot_recommendations,
    sector_recommendation_counts,
)


def test_log_snapshot_recommendations_persists_option_context():
    db_path = _test_db_path()
    snapshot = LiveSignalSnapshot(
        as_of="2026-06-17T09:15:00-05:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
        sectors=[SectorSignal("2026-06-17", "Semiconductors", "SMH", 91.0, 1, True, 0.02, 0.08, 0.15)],
        universe=[StockSignal("AMD", "Semiconductors", 88.0, 2, True, 180.0, 0.9)],
        options=[
            OptionSignal(
                "AMD",
                "AMD260717C180",
                "20260717",
                180.0,
                "C",
                6.0,
                6.2,
                6.1,
                0.56,
                0.03,
                -0.08,
                0.21,
                0.37,
                2400,
                30,
                92.5,
            )
        ],
        risk=[RiskDecision("AMD", True, ["RISK_ALLOWED"], 0.85, "Manual validation required.")],
    )

    logged = log_snapshot_recommendations(snapshot, str(db_path))

    rows = list_recommendations(str(db_path))
    assert logged == 1
    assert rows[0]["ticker"] == "AMD"
    assert rows[0]["sector"] == "Semiconductors"
    assert rows[0]["sector_rank"] == 1
    assert rows[0]["stock_rank"] == 2
    assert rows[0]["right"] == "CALL"
    assert rows[0]["recommendation_type"] == "BUY_CALL"
    assert rows[0]["market_regime"] == "risk-on"


def test_recommendation_queries_support_detail_and_sector_counts():
    db_path = _test_db_path()
    snapshot = LiveSignalSnapshot(
        as_of="2026-06-17T09:15:00-05:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
        sectors=[SectorSignal("2026-06-17", "Technology", "XLK", 80.0, 2, True, 0.01, 0.04, 0.11)],
        universe=[StockSignal("MSFT", "Technology", 85.0, 1, True, 450.0, 0.8)],
        options=[
            OptionSignal("MSFT", "MSFT260717C450", "20260717", 450.0, "CALL", 8.0, 8.4, 8.2, 0.6, 0.02, -0.06, 0.18, 0.28, 1500, 30, 89.0)
        ],
        risk=[RiskDecision("MSFT", False, ["WATCH"], 0.0, "Watch only.")],
    )
    log_snapshot_recommendations(snapshot, str(db_path))

    rows = list_recommendations(str(db_path), ticker="MSFT")
    detail = get_recommendation(str(db_path), rows[0]["id"])
    sectors = sector_recommendation_counts(str(db_path))

    assert detail is not None
    assert detail["option_symbol"] == "MSFT260717C450"
    assert detail["recommendation_type"] == "WATCH"
    assert sectors == [
        {
            "sector": "Technology",
            "recommendation_count": 1,
            "average_score": 89.0,
            "latest_timestamp": "2026-06-17T09:15:00-05:00",
        }
    ]


def test_log_snapshot_recommendations_skips_unchanged_records():
    db_path = _test_db_path()
    snapshot = LiveSignalSnapshot(
        as_of="2026-06-17T09:15:00-05:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
        sectors=[SectorSignal("2026-06-17", "Technology", "XLK", 80.0, 2, True, 0.01, 0.04, 0.11)],
        universe=[StockSignal("MSFT", "Technology", 85.0, 1, True, 450.0, 0.8)],
        options=[
            OptionSignal("MSFT", "MSFT260717C450", "20260717", 450.0, "CALL", 8.0, 8.4, 8.2, 0.6, 0.02, -0.06, 0.18, 0.28, 1500, 30, 89.0)
        ],
        risk=[RiskDecision("MSFT", True, ["RISK_ALLOWED"], 0.85, "Manual validation required.")],
    )
    changed_snapshot = LiveSignalSnapshot(
        as_of="2026-06-17T09:45:00-05:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
        sectors=snapshot.sectors,
        universe=snapshot.universe,
        options=[
            OptionSignal("MSFT", "MSFT260717C450", "20260717", 450.0, "CALL", 8.0, 8.4, 8.2, 0.6, 0.02, -0.06, 0.18, 0.28, 1500, 30, 91.0)
        ],
        risk=snapshot.risk,
    )

    assert log_snapshot_recommendations(snapshot, str(db_path)) == 1
    assert log_snapshot_recommendations(snapshot, str(db_path)) == 0
    assert log_snapshot_recommendations(changed_snapshot, str(db_path)) == 1
    assert len(list_recommendations(str(db_path))) == 2


def test_recommendation_api_lists_persisted_records():
    db_path = _test_db_path()
    snapshot = LiveSignalSnapshot(
        as_of="2026-06-17T09:15:00-05:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
        sectors=[SectorSignal("2026-06-17", "Healthcare", "XLV", 75.0, 3, True, 0.01, 0.03, 0.08)],
        universe=[StockSignal("LLY", "Healthcare", 79.0, 2, True, 900.0, 0.7)],
        options=[
            OptionSignal("LLY", "LLY260717C900", "20260717", 900.0, "C", 12.0, 12.6, 12.3, 0.58, 0.01, -0.09, 0.25, 0.32, 900, 30, 84.0)
        ],
        risk=[RiskDecision("LLY", True, ["RISK_ALLOWED"], 0.85, "Manual validation required.")],
    )
    log_snapshot_recommendations(snapshot, str(db_path))
    app = create_app(
        {
            "live": {"provider": "yahoo", "allow_order_placement": False},
            "recommendation_logging": {"enabled": True, "database_path": str(db_path)},
        }
    )

    response = TestClient(app).get("/api/recommendations")

    assert response.status_code == 200
    assert response.json()[0]["ticker"] == "LLY"


def _test_db_path() -> Path:
    return Path("data") / f"test_option_alpha_{uuid4().hex}.db"
