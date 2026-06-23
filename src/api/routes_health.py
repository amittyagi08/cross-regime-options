from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict:
    config = request.app.state.config
    live = config.get("live", {})
    return {
        "status": "ok",
        "mode": "live-validation",
        "provider": live.get("provider", "yahoo"),
        "allow_order_placement": bool(live.get("allow_order_placement", False)),
    }
