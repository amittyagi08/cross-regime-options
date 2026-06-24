from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.ultra_short.service import build_ultra_short_snapshot


router = APIRouter()


@router.get("/ultra-short", response_class=HTMLResponse)
def ultra_short_portal() -> HTMLResponse:
    template_path = Path(__file__).resolve().parents[1] / "web" / "templates" / "ultra_short.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@router.get("/api/ultra-short/snapshot")
def ultra_short_snapshot(request: Request) -> dict:
    return build_ultra_short_snapshot(request.app.state.config)


@router.get("/api/ultra-short/candidates")
def ultra_short_candidates(request: Request) -> dict:
    snapshot = build_ultra_short_snapshot(request.app.state.config)
    return {
        "as_of": snapshot["as_of"],
        "call_setups": snapshot["call_setups"],
        "put_setups": snapshot["put_setups"],
    }


@router.get("/api/ultra-short/paper-trades")
def ultra_short_paper_trades(request: Request) -> dict:
    snapshot = build_ultra_short_snapshot(request.app.state.config)
    return {
        "as_of": snapshot["as_of"],
        "active_trades": snapshot["active_trades"],
        "closed_trades": snapshot["closed_trades"],
    }


@router.get("/api/ultra-short/marks")
def ultra_short_marks(request: Request) -> dict:
    snapshot = build_ultra_short_snapshot(request.app.state.config)
    return {
        "as_of": snapshot["as_of"],
        "recent_marks": snapshot["recent_marks"],
    }
