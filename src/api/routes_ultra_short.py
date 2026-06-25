from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from src.live.signal_service import load_latest_snapshot
from src.ultra_short.lifecycle import refresh_ultra_short_lifecycle
from src.ultra_short.reporting import build_ultra_short_analytics, export_ultra_short_reports
from src.ultra_short.service import build_ultra_short_snapshot
from src.ultra_short.repository import (
    OPEN,
    approve_ultra_short_candidate,
    list_review_required_candidates,
    list_ultra_short_candidates,
    list_ultra_short_paper_trades,
    list_ultra_short_trade_marks,
    persist_ultra_short_snapshot,
    reject_ultra_short_candidate,
    ultra_short_db_path,
)


router = APIRouter()


@router.get("/ultra-short", response_class=HTMLResponse)
def ultra_short_portal() -> HTMLResponse:
    template_path = Path(__file__).resolve().parents[1] / "web" / "templates" / "ultra_short.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@router.get("/api/ultra-short/snapshot")
def ultra_short_snapshot(request: Request) -> dict:
    live_snapshot = load_latest_snapshot(request.app.state.config)
    snapshot = build_ultra_short_snapshot(request.app.state.config, live_snapshot)
    db_path = ultra_short_db_path(request.app.state.config)
    persist_ultra_short_snapshot(snapshot, db_path)
    if live_snapshot is not None:
        result = refresh_ultra_short_lifecycle(live_snapshot, snapshot, db_path, request.app.state.config)
        snapshot["lifecycle"] = {
            "inspected": result.inspected,
            "marked": result.marked,
            "closed": result.closed,
        }
    snapshot["active_trades"] = list_ultra_short_paper_trades(db_path, state=OPEN)
    snapshot["closed_trades"] = list_ultra_short_paper_trades(db_path, state="CLOSED")
    snapshot["recent_marks"] = list_ultra_short_trade_marks(db_path)
    return snapshot


@router.get("/api/ultra-short/candidates")
def ultra_short_candidates(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict]:
    return list_ultra_short_candidates(ultra_short_db_path(request.app.state.config), status=status, limit=limit)


@router.get("/api/ultra-short/review-required")
def ultra_short_review_required(request: Request) -> list[dict]:
    return list_review_required_candidates(ultra_short_db_path(request.app.state.config))


@router.post("/api/ultra-short/candidates/{candidate_id}/approve")
async def approve_ultra_short_for_paper_trade(request: Request, candidate_id: int) -> dict:
    payload = await request.json()
    try:
        candidate = approve_ultra_short_candidate(
            ultra_short_db_path(request.app.state.config),
            candidate_id,
            approved_at=payload.get("approved_at"),
            entry_price=payload.get("entry_price"),
            review_notes=payload.get("review_notes"),
            override_reason=payload.get("override_reason"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "approved", "candidate": candidate}


@router.post("/api/ultra-short/candidates/{candidate_id}/reject")
async def reject_ultra_short_for_paper_trade(request: Request, candidate_id: int) -> dict:
    payload = await request.json()
    try:
        candidate = reject_ultra_short_candidate(
            ultra_short_db_path(request.app.state.config),
            candidate_id,
            rejected_at=payload.get("rejected_at"),
            rejection_reason=payload.get("reason") or payload.get("rejection_reason"),
            review_notes=payload.get("review_notes") or payload.get("notes"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "rejected", "candidate": candidate}


@router.get("/api/ultra-short/paper-trades")
def ultra_short_paper_trades(request: Request) -> dict:
    return {
        "active_trades": list_ultra_short_paper_trades(ultra_short_db_path(request.app.state.config), state=OPEN),
        "closed_trades": list_ultra_short_paper_trades(ultra_short_db_path(request.app.state.config), state="CLOSED"),
    }


@router.get("/api/ultra-short/marks")
def ultra_short_marks(request: Request) -> dict:
    return {
        "recent_marks": list_ultra_short_trade_marks(ultra_short_db_path(request.app.state.config)),
    }


@router.get("/api/ultra-short/analytics")
def ultra_short_analytics(request: Request) -> dict:
    return build_ultra_short_analytics(ultra_short_db_path(request.app.state.config))


@router.post("/api/ultra-short/exports")
def ultra_short_exports(request: Request) -> dict:
    return export_ultra_short_reports(ultra_short_db_path(request.app.state.config), request.app.state.config)
