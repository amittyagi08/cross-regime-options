from __future__ import annotations

import json

import pandas as pd

from src.live.live_data_provider import _date_column
from src.live.live_config import assert_live_safety
from src.live.signal_service import (
    _contract_score_breakdown,
    _delta_score,
    _dte_score,
    _liquidity_score,
    _with_live_quote,
    save_snapshot,
)
from src.live.signal_snapshot import LiveSignalSnapshot, OptionSignal, RiskDecision, SectorSignal, StockSignal
from src.live.validation_journal import append_journal_entry, load_journal
from src.api.app import create_app


def test_live_safety_rejects_order_placement():
    config = {"live": {"allow_order_placement": True}}

    try:
        assert_live_safety(config)
    except ValueError as exc:
        assert "allow_order_placement=false" in str(exc)
    else:
        raise AssertionError("live dashboard accepted order placement")


def test_yahoo_date_index_normalization_shape():
    raw = pd.DataFrame({"Close": [100.0]}, index=pd.DatetimeIndex(["2026-04-30"], name="Date"))
    frame = raw.reset_index().rename(columns={column: str(column).lower() for column in raw.reset_index().columns})

    assert _date_column(frame) == "date"


def test_snapshot_saves_json_and_csv(tmp_path):
    json_path = tmp_path / "snapshot.json"
    csv_path = tmp_path / "snapshot.csv"
    snapshot = LiveSignalSnapshot(
        as_of="2026-04-30T12:00:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
        sectors=[SectorSignal("2026-04-30", "Tech", "XLK", 90.0, 1, True, 0.01, 0.05, 0.12)],
        universe=[StockSignal("MSFT", "Tech", 80.0, 1, True, 400.0, 0.8)],
        options=[OptionSignal("MSFT", "MSFT 20260515 400C", "20260515", 400.0, "C", 5.0, 5.2, 5.1, 0.6, 0.01, -0.05, 0.02, 0.3, 1000, 15, 92.0)],
        risk=[RiskDecision("MSFT", True, ["RISK_ALLOWED"], 0.85, "Manual validation required.")],
    )
    config = {
        "live": {
            "snapshot_json_path": str(json_path),
            "snapshot_csv_path": str(csv_path),
            "dashboard_log_path": str(tmp_path / "dashboard.jsonl"),
        }
    }

    save_snapshot(snapshot, config)

    assert json.loads(json_path.read_text(encoding="utf-8"))["provider"] == "yahoo"
    assert "section" in csv_path.read_text(encoding="utf-8")


def test_live_option_quote_fallback_uses_last_price():
    row = _with_live_quote({"bid": 0, "ask": 0, "lastPrice": 4.0})

    assert row["mid"] == 4.0
    assert row["bid"] == 3.8
    assert row["ask"] == 4.2
    assert row["quote_quality"] == "fallback"


def test_contract_score_breakdown_explains_components():
    breakdown = _contract_score_breakdown(
        liquidity_score=1.0,
        momentum_score=0.8,
        theta_efficiency_score=0.7,
        delta_score=1.0,
        iv_score=0.6,
        dte_score=1.0,
    )

    assert breakdown["liquidity"] == 25
    assert breakdown["momentum"] == 16
    assert breakdown["theta_efficiency"] == 14
    assert breakdown["delta"] == 15
    assert breakdown["iv"] == 6
    assert breakdown["dte"] == 10
    assert sum(breakdown.values()) == 86


def test_contract_component_scores_cover_realistic_preferences():
    assert _delta_score(0.60) == 1.0
    assert _delta_score(0.52) == 0.75
    assert _delta_score(0.90) == 0.35
    assert _dte_score(30) == 1.0
    assert _dte_score(18) == 0.7
    assert _dte_score(5) == 0.4
    assert _liquidity_score(5.0, 5.4, 5.2, 1000) > _liquidity_score(5.0, 7.0, 6.0, 50)


def test_validation_journal_appends_and_loads(tmp_path):
    path = tmp_path / "journal.csv"

    saved = append_journal_entry(
        {
            "ticker": "MSFT",
            "contract_symbol": "MSFT 20260515 400C",
            "risk_allowed": True,
            "platform_validated": True,
            "chart_validated": True,
            "trade_taken": False,
            "manual_notes": "Watching only.",
        },
        str(path),
    )

    journal = load_journal(str(path))
    assert saved["ticker"] == "MSFT"
    assert journal.iloc[0]["manual_notes"] == "Watching only."


def test_health_endpoint_reports_live_validation_mode():
    from fastapi.testclient import TestClient

    app = create_app({"live": {"provider": "yahoo", "allow_order_placement": False}})
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "mode": "live-validation",
        "provider": "yahoo",
        "allow_order_placement": False,
    }


def test_refresh_endpoint_falls_back_to_latest_snapshot(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    json_path = tmp_path / "snapshot.json"
    csv_path = tmp_path / "snapshot.csv"
    config = {
        "live": {
            "provider": "yahoo",
            "allow_order_placement": False,
            "snapshot_json_path": str(json_path),
            "snapshot_csv_path": str(csv_path),
            "dashboard_log_path": str(tmp_path / "dashboard.jsonl"),
        }
    }
    snapshot = LiveSignalSnapshot(
        as_of="2026-04-30T12:00:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
    )
    save_snapshot(snapshot, config)

    def fail_scan(self):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("src.api.routes_signals.LiveSignalService.run_live_scan", fail_scan)
    response = TestClient(create_app(config)).get("/api/signals/refresh")

    assert response.status_code == 200
    assert response.json()["as_of"] == "2026-04-30T12:00:00"
    assert "network unavailable" in response.json()["refresh_error"]
