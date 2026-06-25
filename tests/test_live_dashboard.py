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
from src.ultra_short.repository import (
    approve_ultra_short_candidate,
    close_ultra_short_trade,
    list_ultra_short_candidates,
    list_review_required_candidates,
    list_ultra_short_paper_trades,
    list_ultra_short_trade_marks,
    persist_ultra_short_snapshot,
    reject_ultra_short_candidate,
)
from src.ultra_short.lifecycle import refresh_ultra_short_lifecycle
from src.ultra_short.reporting import build_ultra_short_analytics, export_ultra_short_reports
from src.ultra_short.service import build_ultra_short_snapshot
from src.live.validation_journal import append_journal_entry, load_journal
from src.api.app import create_app


ULTRA_SHORT_NO_PUT_FETCH = {"ultra_short": {"fetch_put_contracts": False}}


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


def test_ultra_short_portal_routes_wait_for_live_snapshot(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(
        create_app(
            {
                "live": {
                    "provider": "yahoo",
                    "allow_order_placement": False,
                    "snapshot_json_path": str(tmp_path / "missing_snapshot.json"),
                },
                "ultra_short": {"database_path": str(tmp_path / "ultra_short.db")},
            }
        )
    )
    page = client.get("/ultra-short")
    snapshot = client.get("/api/ultra-short/snapshot")

    assert page.status_code == 200
    assert "Ultra-Short Trade Lab" in page.text
    assert snapshot.status_code == 200
    payload = snapshot.json()
    assert payload["status"] == "waiting_for_live_snapshot"
    assert payload["call_setups"] == []
    assert payload["put_setups"] == []
    assert "CALL_TRIGGERED" in payload["states"]


def test_ultra_short_snapshot_reuses_live_snapshot_data():
    live_snapshot = LiveSignalSnapshot(
        as_of="2026-06-24T14:30:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
        sectors=[
            SectorSignal("2026-06-24", "Technology", "XLK", 86.0, 1, True, 0.025, 0.06, 0.15),
            SectorSignal("2026-06-24", "Healthcare", "XLV", 42.0, 2, False, -0.012, -0.01, 0.03),
        ],
        universe=[
            StockSignal("MSFT", "Technology", 84.0, 1, True, 450.0, 0.88),
            StockSignal("MRNA", "Healthcare", 38.0, 5, False, 30.0, 0.25),
        ],
        options=[
            OptionSignal(
                "MSFT",
                "MSFT 20260717 450C",
                "20260717",
                450.0,
                "C",
                8.0,
                8.4,
                8.2,
                0.61,
                0.01,
                -0.04,
                0.02,
                0.32,
                1400,
                23,
                91.0,
            )
        ],
    )

    payload = build_ultra_short_snapshot({"ultra_short": {"max_put_setups": 4, "fetch_put_contracts": False}}, live_snapshot)

    assert payload["status"] == "phase_5_live_snapshot"
    assert payload["market_bias"]["mode"] == "CALL_BIASED"
    assert payload["intraday_sectors"][0]["sector"] == "Technology"
    assert payload["call_setups"][0]["ticker"] == "MSFT"
    assert payload["call_setups"][0]["setup_state"] in {"CALL_SETUP_FORMING", "CALL_TRIGGERED"}
    assert payload["put_setups"][0]["direction"] == "PUT"
    assert payload["put_setups"][0]["setup_state"] in {"PUT_WATCH", "PUT_SETUP_FORMING", "PUT_TRIGGERED"}


def test_ultra_short_put_setup_uses_live_put_contract(monkeypatch):
    put_option = OptionSignal(
        "MRNA",
        "MRNA260717P00030000",
        "20260717",
        30.0,
        "P",
        2.0,
        2.2,
        2.1,
        -0.58,
        0.01,
        -0.02,
        0.01,
        0.45,
        800,
        23,
        88.0,
    )

    def fake_put_option(stock, config):
        return put_option if stock.ticker == "MRNA" else None

    monkeypatch.setattr("src.ultra_short.service._best_live_put_option", fake_put_option)

    payload = build_ultra_short_snapshot({"ultra_short": {"max_put_setups": 4}}, _phase3_live_snapshot())
    mrna_put = next(row for row in payload["put_setups"] if row["ticker"] == "MRNA")

    assert mrna_put["contract_symbol"] == "MRNA260717P00030000"
    assert mrna_put["right"] == "P"
    assert mrna_put["suggested_premium"] == 2.1
    assert mrna_put["delta"] == -0.58


def test_contract_backed_put_watch_persists_as_review_required(monkeypatch, tmp_path):
    put_option = OptionSignal(
        "MRNA",
        "MRNA260717P00030000",
        "20260717",
        30.0,
        "P",
        2.0,
        2.2,
        2.1,
        -0.58,
        0.01,
        -0.02,
        0.01,
        0.45,
        800,
        23,
        88.0,
    )

    monkeypatch.setattr(
        "src.ultra_short.service._best_live_put_option",
        lambda stock, config: put_option if stock.ticker == "MRNA" else None,
    )
    db_path = str(tmp_path / "ultra_short.db")
    snapshot = build_ultra_short_snapshot({"ultra_short": {"max_put_setups": 4}}, _phase3_live_snapshot())

    persist_ultra_short_snapshot(snapshot, db_path)
    put_row = next(row for row in list_review_required_candidates(db_path) if row["ticker"] == "MRNA")

    assert put_row["status"] == "REVIEW_REQUIRED"
    assert put_row["contract_symbol"] == "MRNA260717P00030000"


def test_ultra_short_repository_persists_review_and_paper_trade(tmp_path):
    db_path = str(tmp_path / "ultra_short.db")
    snapshot = build_ultra_short_snapshot(ULTRA_SHORT_NO_PUT_FETCH, _phase3_live_snapshot())

    persisted = persist_ultra_short_snapshot(snapshot, db_path)
    review_rows = list_review_required_candidates(db_path)

    assert persisted >= 1
    assert review_rows
    approved = approve_ultra_short_candidate(
        db_path,
        review_rows[0]["id"],
        review_notes="VWAP trigger, invalidation, stop, and time rule checked.",
    )
    trades = list_ultra_short_paper_trades(db_path, state="OPEN")

    assert approved["status"] == "OPEN"
    assert trades[0]["candidate_id"] == approved["id"]


def test_ultra_short_repository_rejects_review_candidate(tmp_path):
    db_path = str(tmp_path / "ultra_short.db")
    persist_ultra_short_snapshot(build_ultra_short_snapshot(ULTRA_SHORT_NO_PUT_FETCH, _phase3_live_snapshot()), db_path)
    candidate = list_review_required_candidates(db_path)[0]

    rejected = reject_ultra_short_candidate(
        db_path,
        candidate["id"],
        rejection_reason="chart_invalidated",
        review_notes="Setup failed before confirmation.",
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "chart_invalidated"


def test_ultra_short_api_approves_persisted_candidate(tmp_path):
    from fastapi.testclient import TestClient

    db_path = str(tmp_path / "ultra_short.db")
    persist_ultra_short_snapshot(build_ultra_short_snapshot(ULTRA_SHORT_NO_PUT_FETCH, _phase3_live_snapshot()), db_path)
    candidate = list_review_required_candidates(db_path)[0]
    client = TestClient(
        create_app(
            {
                "live": {"provider": "yahoo", "allow_order_placement": False},
                "ultra_short": {"database_path": db_path},
            }
        )
    )

    response = client.post(
        f"/api/ultra-short/candidates/{candidate['id']}/approve",
        json={"review_notes": "Validated setup and risk plan."},
    )

    assert response.status_code == 200
    assert response.json()["candidate"]["status"] == "OPEN"
    assert client.get("/api/ultra-short/paper-trades").json()["active_trades"][0]["candidate_id"] == candidate["id"]


def test_ultra_short_lifecycle_records_mark_and_moves_stop(tmp_path):
    db_path = str(tmp_path / "ultra_short.db")
    opening_snapshot = build_ultra_short_snapshot(ULTRA_SHORT_NO_PUT_FETCH, _phase3_live_snapshot())
    persist_ultra_short_snapshot(opening_snapshot, db_path)
    candidate = list_review_required_candidates(db_path)[0]
    approve_ultra_short_candidate(
        db_path,
        candidate["id"],
        entry_price=8.0,
        review_notes="Validated setup and risk plan.",
    )
    live_snapshot = _phase4_live_snapshot(bid=9.4)
    ultra_short_snapshot = build_ultra_short_snapshot(ULTRA_SHORT_NO_PUT_FETCH, live_snapshot)

    result = refresh_ultra_short_lifecycle(live_snapshot, ultra_short_snapshot, db_path, {})
    trades = list_ultra_short_paper_trades(db_path, state="OPEN")
    marks = list_ultra_short_trade_marks(db_path)

    assert result.marked == 1
    assert result.closed == 0
    assert trades[0]["pnl_pct"] > 0.15
    assert trades[0]["stop_state"] == "PROTECTED_BREAKEVEN"
    assert marks[0]["signal"] == "HOLD"


def test_ultra_short_lifecycle_closes_profit_target(tmp_path):
    db_path = str(tmp_path / "ultra_short.db")
    opening_snapshot = build_ultra_short_snapshot(ULTRA_SHORT_NO_PUT_FETCH, _phase3_live_snapshot())
    persist_ultra_short_snapshot(opening_snapshot, db_path)
    candidate = list_review_required_candidates(db_path)[0]
    approve_ultra_short_candidate(
        db_path,
        candidate["id"],
        entry_price=8.0,
        review_notes="Validated setup and risk plan.",
    )
    live_snapshot = _phase4_live_snapshot(bid=11.0)
    ultra_short_snapshot = build_ultra_short_snapshot(ULTRA_SHORT_NO_PUT_FETCH, live_snapshot)

    result = refresh_ultra_short_lifecycle(live_snapshot, ultra_short_snapshot, db_path, {})
    open_trades = list_ultra_short_paper_trades(db_path, state="OPEN")
    closed_trades = list_ultra_short_paper_trades(db_path, state="CLOSED")
    marks = list_ultra_short_trade_marks(db_path)

    assert result.closed == 1
    assert open_trades == []
    assert closed_trades[0]["exit_reason"] == "profit_target"
    assert marks[0]["signal"] == "EXIT"


def test_ultra_short_analytics_and_exports_include_wins_and_rejections(tmp_path):
    db_path = str(tmp_path / "ultra_short.db")
    persist_ultra_short_snapshot(build_ultra_short_snapshot(ULTRA_SHORT_NO_PUT_FETCH, _phase3_live_snapshot()), db_path)
    candidate = list_review_required_candidates(db_path)[0]
    approve_ultra_short_candidate(
        db_path,
        candidate["id"],
        entry_price=8.0,
        review_notes="Validated setup and risk plan.",
    )
    trade = list_ultra_short_paper_trades(db_path, state="OPEN")[0]
    close_ultra_short_trade(
        db_path,
        trade,
        closed_at="2026-06-24T15:00:00",
        exit_price=10.0,
        exit_reason="profit_target",
    )
    rejectable = [row for row in list_ultra_short_candidates(db_path) if row["id"] != candidate["id"]][0]
    reject_ultra_short_candidate(db_path, rejectable["id"], rejection_reason="spread_too_wide")

    analytics = build_ultra_short_analytics(db_path)
    export = export_ultra_short_reports(
        db_path,
        {
            "ultra_short_exports": {
                "candidates_csv": str(tmp_path / "candidates.csv"),
                "trades_csv": str(tmp_path / "trades.csv"),
                "marks_csv": str(tmp_path / "marks.csv"),
                "rejected_csv": str(tmp_path / "rejected.csv"),
                "analytics_json": str(tmp_path / "analytics.json"),
            }
        },
    )

    assert analytics["win_loss"]["closed_trades"] == 1
    assert analytics["win_loss"]["winning_trades"] == 1
    assert analytics["rejections"]["by_reason"]["spread_too_wide"] == 1
    assert export["row_counts"]["rejected"] == 1
    assert (tmp_path / "candidates.csv").exists()
    assert (tmp_path / "analytics.json").exists()


def test_ultra_short_api_returns_analytics_and_exports(tmp_path):
    from fastapi.testclient import TestClient

    db_path = str(tmp_path / "ultra_short.db")
    persist_ultra_short_snapshot(build_ultra_short_snapshot(ULTRA_SHORT_NO_PUT_FETCH, _phase3_live_snapshot()), db_path)
    candidate = list_review_required_candidates(db_path)[0]
    approve_ultra_short_candidate(
        db_path,
        candidate["id"],
        entry_price=8.0,
        review_notes="Validated setup and risk plan.",
    )
    trade = list_ultra_short_paper_trades(db_path, state="OPEN")[0]
    close_ultra_short_trade(
        db_path,
        trade,
        closed_at="2026-06-24T15:00:00",
        exit_price=7.0,
        exit_reason="stop_loss",
    )
    client = TestClient(
        create_app(
            {
                "live": {"provider": "yahoo", "allow_order_placement": False},
                "ultra_short": {"database_path": db_path},
                "ultra_short_exports": {
                    "candidates_csv": str(tmp_path / "api_candidates.csv"),
                    "trades_csv": str(tmp_path / "api_trades.csv"),
                    "marks_csv": str(tmp_path / "api_marks.csv"),
                    "rejected_csv": str(tmp_path / "api_rejected.csv"),
                    "analytics_json": str(tmp_path / "api_analytics.json"),
                },
            }
        )
    )

    analytics = client.get("/api/ultra-short/analytics")
    export = client.post("/api/ultra-short/exports")

    assert analytics.status_code == 200
    assert analytics.json()["win_loss"]["losing_trades"] == 1
    assert export.status_code == 200
    assert export.json()["row_counts"]["trades"] == 1
    assert (tmp_path / "api_analytics.json").exists()


def _phase3_live_snapshot() -> LiveSignalSnapshot:
    return LiveSignalSnapshot(
        as_of="2026-06-24T14:30:00",
        provider="yahoo",
        market_status="validation",
        regime_status="risk-on",
        sectors=[
            SectorSignal("2026-06-24", "Technology", "XLK", 92.0, 1, True, 0.035, 0.07, 0.16),
            SectorSignal("2026-06-24", "Healthcare", "XLV", 42.0, 2, False, -0.012, -0.01, 0.03),
        ],
        universe=[
            StockSignal("MSFT", "Technology", 90.0, 1, True, 450.0, 0.94),
            StockSignal("MRNA", "Healthcare", 38.0, 5, False, 30.0, 0.25),
        ],
        options=[
            OptionSignal(
                "MSFT",
                "MSFT 20260717 450C",
                "20260717",
                450.0,
                "C",
                8.0,
                8.4,
                8.2,
                0.61,
                0.01,
                -0.04,
                0.02,
                0.32,
                1400,
                23,
                96.0,
            )
        ],
    )


def _phase4_live_snapshot(bid: float) -> LiveSignalSnapshot:
    snapshot = _phase3_live_snapshot()
    option = snapshot.options[0]
    return LiveSignalSnapshot(
        as_of="2026-06-24T14:45:00",
        provider=snapshot.provider,
        market_status=snapshot.market_status,
        regime_status=snapshot.regime_status,
        sectors=snapshot.sectors,
        universe=snapshot.universe,
        options=[
            OptionSignal(
                option.ticker,
                option.contract_symbol,
                option.expiry,
                option.strike,
                option.right,
                bid,
                bid + 0.2,
                bid + 0.1,
                option.delta,
                option.gamma,
                option.theta,
                option.vega,
                option.implied_vol,
                option.open_interest,
                option.dte,
                option.total_score,
            )
        ],
    )


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
