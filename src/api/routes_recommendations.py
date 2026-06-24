from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.recommendation_logging import (
    approve_recommendation,
    get_recommendation,
    list_closed_recommendations,
    list_open_recommendations,
    list_open_paper_trades,
    list_paper_trade_marks,
    list_paper_trades,
    list_review_required_recommendations,
    list_recommendations,
    recommendation_db_path,
    reject_recommendation,
    sector_recommendation_counts,
)


router = APIRouter()


@router.get("/api/recommendations")
def recommendations(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    ticker: str | None = Query(default=None),
) -> list[dict]:
    return list_recommendations(recommendation_db_path(request.app.state.config), limit=limit, ticker=ticker)


@router.get("/api/recommendations/sectors")
def recommendation_sectors(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    return sector_recommendation_counts(recommendation_db_path(request.app.state.config), limit=limit)


@router.get("/api/recommendations/open")
def open_recommendations(request: Request) -> list[dict]:
    return list_open_recommendations(recommendation_db_path(request.app.state.config))


@router.get("/api/recommendations/review-required")
def review_required_recommendations(request: Request) -> list[dict]:
    return list_review_required_recommendations(
        recommendation_db_path(request.app.state.config),
        config=request.app.state.config,
    )


@router.get("/api/recommendations/closed")
def closed_recommendations(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict]:
    return list_closed_recommendations(recommendation_db_path(request.app.state.config), limit=limit)


@router.get("/api/paper-trades")
def paper_trades(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict]:
    return list_paper_trades(recommendation_db_path(request.app.state.config), status=status, limit=limit)


@router.get("/api/paper-trades/open")
def open_paper_trades(request: Request) -> list[dict]:
    return list_open_paper_trades(recommendation_db_path(request.app.state.config))


@router.get("/api/paper-trades/marks")
def paper_trade_marks(
    request: Request,
    paper_trade_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    return list_paper_trade_marks(
        recommendation_db_path(request.app.state.config),
        paper_trade_id=paper_trade_id,
        limit=limit,
    )


@router.post("/api/recommendations/{recommendation_id}/approve")
async def approve_recommendation_for_paper_trade(request: Request, recommendation_id: int) -> dict:
    payload = await request.json()
    try:
        approved = approve_recommendation(
            recommendation_db_path(request.app.state.config),
            recommendation_id,
            approved_at=payload.get("approved_at"),
            entry_price=payload.get("entry_price"),
            latest_notes=payload.get("notes") or "Manually approved for paper trade.",
            config=request.app.state.config,
            review_notes=payload.get("review_notes"),
            override_reason=payload.get("override_reason"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "approved", "recommendation": approved}


@router.post("/api/recommendations/{recommendation_id}/reject")
async def reject_recommendation_for_paper_trade(request: Request, recommendation_id: int) -> dict:
    payload = await request.json()
    reason = payload.get("reason") or payload.get("rejection_reason") or "manual_reject"
    try:
        rejected = reject_recommendation(
            recommendation_db_path(request.app.state.config),
            recommendation_id,
            rejected_at=payload.get("rejected_at"),
            rejection_reason=reason,
            latest_notes=payload.get("notes") or f"Rejected during manual review: {reason}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "rejected", "recommendation": rejected}


@router.get("/api/recommendations/{recommendation_id}")
def recommendation_detail(request: Request, recommendation_id: int) -> dict:
    recommendation = get_recommendation(recommendation_db_path(request.app.state.config), recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return recommendation
