from __future__ import annotations

from fastapi import APIRouter, Request

from src.live.signal_service import LiveSignalService, load_latest_snapshot


router = APIRouter()


def _snapshot_or_refresh(request: Request):
    snapshot = load_latest_snapshot(request.app.state.config)
    if snapshot is None:
        snapshot = LiveSignalService(request.app.state.config).run_live_scan()
    return snapshot


@router.get("/api/signals/latest")
def latest_signals(request: Request) -> dict:
    return _snapshot_or_refresh(request).to_dict()


@router.get("/api/signals/refresh")
def refresh_signals(request: Request) -> dict:
    try:
        snapshot = LiveSignalService(request.app.state.config).run_live_scan()
        payload = snapshot.to_dict()
        payload["refresh_error"] = None
        return payload
    except Exception as exc:
        snapshot = load_latest_snapshot(request.app.state.config)
        if snapshot is None:
            raise
        payload = snapshot.to_dict()
        payload["refresh_error"] = f"Fresh Yahoo scan failed; showing latest saved snapshot. {type(exc).__name__}: {exc}"
        return payload


@router.get("/api/sectors")
def sectors(request: Request) -> list[dict]:
    return [item.__dict__ for item in _snapshot_or_refresh(request).sectors]


@router.get("/api/universe")
def universe(request: Request) -> list[dict]:
    return [item.__dict__ for item in _snapshot_or_refresh(request).universe]


@router.get("/api/options")
def options(request: Request) -> list[dict]:
    return [item.__dict__ for item in _snapshot_or_refresh(request).options]


@router.get("/api/risk")
def risk(request: Request) -> list[dict]:
    return [item.__dict__ for item in _snapshot_or_refresh(request).risk]
