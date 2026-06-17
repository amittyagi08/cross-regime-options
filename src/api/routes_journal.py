from __future__ import annotations

from fastapi import APIRouter, Request

from src.live.signal_service import _append_log
from src.live.validation_journal import append_journal_entry, load_journal


router = APIRouter()


@router.get("/api/journal")
def get_journal(request: Request) -> list[dict]:
    path = request.app.state.config.get("manual_validation", {}).get("journal_path", "data/validation_journal.csv")
    return load_journal(path).fillna("").to_dict("records")


@router.post("/api/journal")
async def post_journal(request: Request) -> dict:
    entry = await request.json()
    path = request.app.state.config.get("manual_validation", {}).get("journal_path", "data/validation_journal.csv")
    saved = append_journal_entry(entry, path)
    _append_log("journal_entry_saved", request.app.state.config)
    return {"status": "saved", "entry": saved}
