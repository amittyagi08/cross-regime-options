from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.day_trading.service import build_day_trading_snapshot


router = APIRouter()


@router.get("/day-trading", response_class=HTMLResponse)
def day_trading_dashboard() -> HTMLResponse:
    template_path = Path(__file__).resolve().parents[1] / "web" / "templates" / "day_trading.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@router.get("/api/day-trading/snapshot")
def day_trading_snapshot(request: Request) -> dict:
    return build_day_trading_snapshot(request.app.state.config)
