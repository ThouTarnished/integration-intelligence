"""Application factory: wires configuration, middleware, the API, the live hub and the dashboard."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from . import __version__
from .config import WEB_DIR, settings
from .database import SessionLocal, User, init_db
from .live import hub, traffic
from .observability import RequestContextMiddleware
from .routes import api_router
from .seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("iip")


class RevalidatingStaticFiles(StaticFiles):
    """The frontend's files aren't fingerprinted, so browsers are told to revalidate them on every load
    (cheap: an unchanged file is a 304) instead of possibly running a stale copy after an update."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


TAGS = [
    {"name": "events", "description": "Ingest and search identity & risk events."},
    {"name": "incidents", "description": "Correlated incidents and triage."},
    {"name": "users", "description": "Customer risk profiles."},
    {"name": "risk engine", "description": "The rulebook and what-if scoring."},
    {"name": "simulation", "description": "Scenario replay, live traffic and demo reset."},
    {"name": "integration", "description": "Health, metrics and the live SSE stream."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(User)):
            log.info("Empty database: seeding synthetic NovaBank data")
            seed(db)
    hub.bind(asyncio.get_running_loop())
    yield
    await traffic.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Integration Intelligence Platform", version=__version__, lifespan=lifespan, openapi_tags=TAGS,
        description="Identity & risk-events integration for the fictional NovaBank: ingestion, explainable risk "
                    "scoring, incident correlation, live streaming and an AI analyst. All data is synthetic.",
    )
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "PATCH"], allow_headers=["*"])
    app.add_middleware(RequestContextMiddleware)  # added last = outermost: times and tags everything

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error", exc_info=exc)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    app.include_router(api_router)
    app.mount("/static", RevalidatingStaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> str:
        page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        # Demo convenience only (see README → Security): the page receives the key so the
        # browser can call write endpoints. With IIP_DEMO_MODE=false the user is asked for it.
        return page.replace("__IIP_API_KEY__", settings.api_key if settings.demo_mode else "")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(WEB_DIR / "assets" / "favicon.svg", media_type="image/svg+xml")

    return app


app = create_app()
