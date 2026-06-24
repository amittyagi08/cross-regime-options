from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.live.signal_snapshot import LiveSignalSnapshot, OptionSignal, RiskDecision, SectorSignal, StockSignal
from src.live.recommendation_lifecycle import refresh_open_recommendations
from src.recommendation_logging import (
    approve_recommendation,
    get_recommendation,
    list_closed_recommendations,
    list_open_recommendations,
    list_open_paper_trades,
    list_paper_trade_marks,
    list_review_required_recommendations,
    list_recommendations,
    log_snapshot_recommendations,
    reject_recommendation,
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
    assert rows[0]["status"] == "REVIEW_REQUIRED"
    assert rows[0]["entry_price"] is None
    assert rows[0]["current_price"] is None
    assert rows[0]["opened_at"] is None
    assert rows[0]["market_regime"] == "risk-on"
    assert rows[0]["trade_reason"]
    assert rows[0]["entry_trigger"] == "manual_review_confirmed"
    assert rows[0]["suggested_limit_price"] == 6.2
    assert rows[0]["profit_target_pct"] == 0.40
    assert rows[0]["stop_loss_pct"] == -0.25
    assert rows[0]["time_stop_rule"] == "Exit after 5 holding days"
    assert rows[0]["technical_invalidation_rule"]
    assert rows[0]["max_dollar_risk"] == pytest.approx(620.0)
    assert rows[0]["risk_notes"] == "Manual validation required."
    assert rows[0]["plan_complete"] == 1


def test_approve_recommendation_creates_open_paper_trade():
    db_path = _test_db_path()
    snapshot = _amd_snapshot(score=92.5)

    assert log_snapshot_recommendations(snapshot, str(db_path)) == 1
    review_rows = list_review_required_recommendations(str(db_path))
    approved = approve_recommendation(
        str(db_path),
        review_rows[0]["id"],
        approved_at="2026-06-17T09:20:00-05:00",
        latest_notes="Manual approval test.",
        review_notes="Broker contract, premium, spread, and chart validated.",
    )

    open_rows = list_open_recommendations(str(db_path))
    paper_rows = list_open_paper_trades(str(db_path))
    assert approved["status"] == "OPEN"
    assert len(open_rows) == 1
    assert len(paper_rows) == 1
    assert paper_rows[0]["recommendation_id"] == approved["id"]
    assert paper_rows[0]["option_symbol"] == "AMD260717C180"
    assert open_rows[0]["option_symbol"] == "AMD260717C180"
    assert open_rows[0]["entry_price"] == 6.2
    assert open_rows[0]["opened_at"] == "2026-06-17T09:20:00-05:00"
    assert open_rows[0]["lifecycle_state"] == "OPEN_INITIAL_RISK"
    assert open_rows[0]["high_water_mark"] == 6.2
    assert open_rows[0]["stop_price"] == pytest.approx(4.65)
    assert open_rows[0]["review_notes"] == "Broker contract, premium, spread, and chart validated."


def test_approve_recommendation_requires_review_notes():
    db_path = _test_db_path()
    log_snapshot_recommendations(_amd_snapshot(score=92.5), str(db_path))
    review_rows = list_review_required_recommendations(str(db_path))

    with pytest.raises(ValueError, match="review notes"):
        approve_recommendation(str(db_path), review_rows[0]["id"])


def test_auto_open_can_only_happen_when_manual_approval_disabled():
    db_path = _test_db_path()

    assert log_snapshot_recommendations(
        _amd_snapshot(score=92.5),
        str(db_path),
        {"paper_trading": {"auto_open_paper_trades": True, "require_manual_approval": False}},
    ) == 1

    assert len(list_open_recommendations(str(db_path))) == 1


def test_reject_recommendation_marks_pending_plan_rejected():
    db_path = _test_db_path()
    log_snapshot_recommendations(_amd_snapshot(), str(db_path))
    review_rows = list_review_required_recommendations(str(db_path))

    rejected = reject_recommendation(
        str(db_path),
        review_rows[0]["id"],
        rejected_at="2026-06-17T09:22:00-05:00",
        rejection_reason="spread_too_wide",
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["rejected_at"] == "2026-06-17T09:22:00-05:00"
    assert rejected["rejection_reason"] == "spread_too_wide"
    assert list_review_required_recommendations(str(db_path)) == []


def test_refresh_open_recommendations_closes_profit_target():
    db_path = _test_db_path()
    log_snapshot_recommendations(_amd_snapshot(ask=5.0), str(db_path))
    approve_recommendation(
        str(db_path),
        list_review_required_recommendations(str(db_path))[0]["id"],
        review_notes="Validated before approval.",
    )

    result = refresh_open_recommendations(
        _amd_snapshot(as_of="2026-06-18T09:15:00-05:00", bid=7.2, ask=7.4, mid=7.3),
        str(db_path),
        {"exit": {"profit_target_pct": 0.40, "stop_loss_pct": -0.25, "max_holding_days": 5}},
    )

    closed_rows = list_closed_recommendations(str(db_path))
    assert result.updated == 1
    assert result.closed == 1
    assert closed_rows[0]["close_reason"] == "profit_target"
    assert closed_rows[0]["close_price"] == 7.2
    assert closed_rows[0]["pnl_pct"] == pytest.approx(0.44)
    marks = list_paper_trade_marks(str(db_path))
    assert marks[0]["exit_signal"] == "EXIT"
    assert marks[0]["signal_reason"] == "profit_target"
    assert marks[0]["pnl_pct"] == pytest.approx(0.44)
    assert list_open_paper_trades(str(db_path)) == []


def test_refresh_open_recommendations_closes_stop_loss():
    db_path = _test_db_path()
    log_snapshot_recommendations(_amd_snapshot(ask=5.0), str(db_path))
    approve_recommendation(
        str(db_path),
        list_review_required_recommendations(str(db_path))[0]["id"],
        review_notes="Validated before approval.",
    )

    refresh_open_recommendations(
        _amd_snapshot(as_of="2026-06-18T09:15:00-05:00", bid=3.7, ask=3.9, mid=3.8),
        str(db_path),
        {"exit": {"profit_target_pct": 0.40, "stop_loss_pct": -0.25, "max_holding_days": 5}},
    )

    closed_rows = list_closed_recommendations(str(db_path))
    assert closed_rows[0]["close_reason"] == "stop_loss"
    assert closed_rows[0]["pnl_pct"] == pytest.approx(-0.26)
    assert closed_rows[0]["lifecycle_state"] == "EXITED"


def test_refresh_open_recommendations_moves_stop_to_breakeven():
    db_path = _test_db_path()
    log_snapshot_recommendations(_amd_snapshot(bid=10.0, ask=10.0, mid=10.0), str(db_path))
    approve_recommendation(
        str(db_path),
        list_review_required_recommendations(str(db_path))[0]["id"],
        review_notes="Validated before approval.",
    )

    refresh_open_recommendations(
        _amd_snapshot(as_of="2026-06-18T09:15:00-05:00", bid=11.2, ask=11.4, mid=11.3),
        str(db_path),
        {"exit": {"profit_target_pct": 1.0, "stop_loss_pct": -0.25, "max_holding_days": 5}},
    )

    open_rows = list_open_recommendations(str(db_path))
    marks = list_paper_trade_marks(str(db_path))
    assert open_rows[0]["lifecycle_state"] == "PROTECTED_BREAKEVEN"
    assert open_rows[0]["high_water_mark"] == 11.2
    assert open_rows[0]["stop_price"] == 10.0
    assert marks[0]["exit_signal"] == "HOLD"
    assert marks[0]["signal_reason"] == "hold"
    assert marks[0]["lifecycle_state"] == "PROTECTED_BREAKEVEN"

    refresh_open_recommendations(
        _amd_snapshot(as_of="2026-06-19T09:15:00-05:00", bid=9.9, ask=10.1, mid=10.0),
        str(db_path),
        {"exit": {"profit_target_pct": 1.0, "stop_loss_pct": -0.25, "max_holding_days": 5}},
    )

    closed_rows = list_closed_recommendations(str(db_path))
    assert closed_rows[0]["close_reason"] == "breakeven_stop"


def test_refresh_open_recommendations_closes_max_holding_days():
    db_path = _test_db_path()
    log_snapshot_recommendations(_amd_snapshot(as_of="2026-06-17T09:15:00-05:00", ask=5.0), str(db_path))
    approve_recommendation(
        str(db_path),
        list_review_required_recommendations(str(db_path))[0]["id"],
        approved_at="2026-06-17T09:15:00-05:00",
        review_notes="Validated before approval.",
    )

    refresh_open_recommendations(
        _amd_snapshot(as_of="2026-06-23T09:15:00-05:00", bid=5.2, ask=5.4, mid=5.3),
        str(db_path),
        {"exit": {"profit_target_pct": 0.40, "stop_loss_pct": -0.25, "max_holding_days": 5}},
    )

    closed_rows = list_closed_recommendations(str(db_path))
    assert closed_rows[0]["close_reason"] == "max_holding_days"


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


def test_log_snapshot_recommendations_updates_same_contract_candidate():
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
    rows = list_recommendations(str(db_path))
    assert len(rows) == 1
    assert rows[0]["recommendation_score"] == 91.0
    assert rows[0]["timestamp"] == "2026-06-17T09:45:00-05:00"


def test_review_required_shows_best_contract_per_ticker():
    db_path = _test_db_path()
    snapshot = LiveSignalSnapshot(
        as_of="2026-06-17T09:15:00-05:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
        sectors=[SectorSignal("2026-06-17", "Technology", "XLK", 80.0, 2, True, 0.01, 0.04, 0.11)],
        universe=[StockSignal("MSFT", "Technology", 85.0, 1, True, 450.0, 0.8)],
        options=[
            OptionSignal("MSFT", "MSFT260717C450", "20260717", 450.0, "CALL", 8.0, 8.4, 8.2, 0.6, 0.02, -0.06, 0.18, 0.28, 1500, 30, 89.0),
            OptionSignal("MSFT", "MSFT260717C455", "20260717", 455.0, "CALL", 6.0, 6.2, 6.1, 0.55, 0.02, -0.05, 0.18, 0.27, 2200, 30, 93.0),
        ],
        risk=[RiskDecision("MSFT", True, ["RISK_ALLOWED"], 0.85, "Manual validation required.")],
    )

    assert log_snapshot_recommendations(snapshot, str(db_path)) == 2

    review_rows = list_review_required_recommendations(str(db_path))
    assert len(review_rows) == 1
    assert review_rows[0]["option_symbol"] == "MSFT260717C455"
    assert review_rows[0]["alternate_contract_count"] == 2


def test_approve_recommendation_blocks_second_open_trade_for_ticker():
    db_path = _test_db_path()
    snapshot = LiveSignalSnapshot(
        as_of="2026-06-17T09:15:00-05:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
        sectors=[SectorSignal("2026-06-17", "Semiconductors", "SMH", 91.0, 1, True, 0.02, 0.08, 0.15)],
        universe=[StockSignal("AMD", "Semiconductors", 88.0, 2, True, 180.0, 0.9)],
        options=[
            OptionSignal("AMD", "AMD260717C180", "20260717", 180.0, "C", 6.0, 6.2, 6.1, 0.56, 0.03, -0.08, 0.21, 0.37, 2400, 30, 92.5),
            OptionSignal("AMD", "AMD260717C185", "20260717", 185.0, "C", 4.0, 4.2, 4.1, 0.50, 0.03, -0.07, 0.20, 0.36, 1800, 30, 88.0),
        ],
        risk=[RiskDecision("AMD", True, ["RISK_ALLOWED"], 0.85, "Manual validation required.")],
    )
    log_snapshot_recommendations(snapshot, str(db_path))
    rows = list_recommendations(str(db_path))

    assert len(rows) == 1
    approve_recommendation(str(db_path), rows[0]["id"], review_notes="Validated before approval.")
    assert list_review_required_recommendations(str(db_path)) == []


def test_review_required_hides_ticker_with_open_trade_when_pyramiding_disabled():
    db_path = _test_db_path()
    first = _amd_snapshot()
    second = _amd_snapshot(
        as_of="2026-06-18T09:15:00-05:00",
        bid=4.0,
        ask=4.2,
        mid=4.1,
        score=95.0,
    )

    log_snapshot_recommendations(first, str(db_path))
    approve_recommendation(
        str(db_path),
        list_review_required_recommendations(str(db_path))[0]["id"],
        review_notes="Validated before approval.",
    )
    log_snapshot_recommendations(second, str(db_path))

    assert list_review_required_recommendations(str(db_path)) == []
    assert all(row["status"] != "REVIEW_REQUIRED" for row in list_recommendations(str(db_path)))


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


def test_recommendation_api_requires_manual_approval_before_open():
    db_path = _test_db_path()
    log_snapshot_recommendations(_amd_snapshot(), str(db_path))
    app = create_app(
        {
            "live": {"provider": "yahoo", "allow_order_placement": False},
            "recommendation_logging": {"enabled": True, "database_path": str(db_path)},
            "paper_trading": {"auto_open_paper_trades": False, "require_manual_approval": True},
        }
    )
    client = TestClient(app)

    review_response = client.get("/api/recommendations/review-required")
    open_response = client.get("/api/recommendations/open")
    approve_response = client.post(
        f"/api/recommendations/{review_response.json()[0]['id']}/approve",
        json={
            "entry_price": 6.2,
            "review_notes": "Broker contract, premium, spread, and chart validated.",
            "notes": "Manual approval test.",
        },
    )

    assert review_response.status_code == 200
    assert open_response.status_code == 200
    assert len(review_response.json()) == 1
    assert open_response.json() == []
    assert approve_response.status_code == 200
    assert approve_response.json()["recommendation"]["status"] == "OPEN"
    assert client.get("/api/recommendations/open").json()[0]["ticker"] == "AMD"


def test_recommendation_api_rejects_pending_trade_plan():
    db_path = _test_db_path()
    log_snapshot_recommendations(_amd_snapshot(), str(db_path))
    app = create_app(
        {
            "live": {"provider": "yahoo", "allow_order_placement": False},
            "recommendation_logging": {"enabled": True, "database_path": str(db_path)},
            "paper_trading": {"auto_open_paper_trades": False, "require_manual_approval": True},
        }
    )
    client = TestClient(app)

    review_response = client.get("/api/recommendations/review-required")
    reject_response = client.post(
        f"/api/recommendations/{review_response.json()[0]['id']}/reject",
        json={"reason": "chart_invalidated"},
    )

    assert reject_response.status_code == 200
    assert reject_response.json()["recommendation"]["status"] == "REJECTED"
    assert reject_response.json()["recommendation"]["rejection_reason"] == "chart_invalidated"
    assert client.get("/api/recommendations/review-required").json() == []


def _test_db_path() -> Path:
    return Path("data") / f"test_option_alpha_{uuid4().hex}.db"


def _amd_snapshot(
    *,
    as_of: str = "2026-06-17T09:15:00-05:00",
    bid: float = 6.0,
    ask: float = 6.2,
    mid: float = 6.1,
    score: float = 92.5,
) -> LiveSignalSnapshot:
    return LiveSignalSnapshot(
        as_of=as_of,
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
                bid,
                ask,
                mid,
                0.56,
                0.03,
                -0.08,
                0.21,
                0.37,
                2400,
                30,
                score,
            )
        ],
        risk=[RiskDecision("AMD", True, ["RISK_ALLOWED"], 0.85, "Manual validation required.")],
    )
