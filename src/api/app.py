from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes_health import router as health_router
from src.api.routes_journal import router as journal_router
from src.api.routes_signals import router as signals_router
from src.config import load_config
from src.live.live_config import assert_live_safety


def create_app(config: dict | None = None) -> FastAPI:
    app = FastAPI(title="Cross Regime Alpha Options Overlay", version="5.0")
    app.state.config = config or load_config()
    assert_live_safety(app.state.config)

    static_path = Path(__file__).resolve().parents[1] / "web" / "static"
    app.mount("/static", StaticFiles(directory=static_path), name="static")
    app.include_router(health_router)
    app.include_router(signals_router)
    app.include_router(journal_router)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> HTMLResponse:
        template_path = Path(__file__).resolve().parents[1] / "web" / "templates" / "dashboard.html"
        return HTMLResponse(template_path.read_text(encoding="utf-8"))

    return app


app = create_app()
