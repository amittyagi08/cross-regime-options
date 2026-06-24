from __future__ import annotations

from datetime import datetime
from typing import Any


ULTRA_SHORT_STATES = [
    "CALL_WATCH",
    "CALL_SETUP_FORMING",
    "CALL_TRIGGERED",
    "PUT_WATCH",
    "PUT_SETUP_FORMING",
    "PUT_TRIGGERED",
    "CHOP_NO_TRADE",
    "EXTENDED_DO_NOT_CHASE",
]


def build_ultra_short_snapshot(config: dict | None = None) -> dict[str, Any]:
    """Return the Phase 1 portal shell payload.

    The ultra-short lab is intentionally separate from the swing recommendation
    workflow. Phase 1 exposes empty structured sections so the portal can be
    developed without changing existing sector-rotation scoring.
    """
    return {
        "as_of": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "portal_shell",
        "mode": "manual_review_only",
        "warning": "Ultra-Short Trade Lab is a separate research portal. No live orders or auto-ordering.",
        "states": ULTRA_SHORT_STATES,
        "market_bias": {
            "mode": "NOT_READY",
            "call_readiness": 0.0,
            "put_readiness": 0.0,
            "notes": "Phase 1 shell only. Intraday market-bias scoring is not connected yet.",
        },
        "intraday_sectors": [],
        "call_setups": [],
        "put_setups": [],
        "active_trades": [],
        "closed_trades": [],
        "recent_marks": [],
        "implementation_phase": {
            "current": "Phase 1 - Portal Shell",
            "next": "Phase 2 - Ultra-Short Snapshot Service",
        },
    }
