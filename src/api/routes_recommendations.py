from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.recommendation_logging import (
    get_recommendation,
    list_closed_recommendations,
    list_open_recommendations,
    list_recommendations,
    recommendation_db_path,
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


@router.get("/api/recommendations/closed")
def closed_recommendations(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict]:
    return list_closed_recommendations(recommendation_db_path(request.app.state.config), limit=limit)


@router.get("/api/recommendations/{recommendation_id}")
def recommendation_detail(request: Request, recommendation_id: int) -> dict:
    recommendation = get_recommendation(recommendation_db_path(request.app.state.config), recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return recommendation
