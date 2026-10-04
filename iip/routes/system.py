"""Integration health, operational metrics and the live event stream."""
from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from .. import __version__, live
from ..config import settings
from ..database import Event
from ..observability import metrics
from .deps import DB

router = APIRouter(tags=["integration"])


def endpoint_catalog(app: FastAPI) -> list[dict]:
    """Self-describing API surface, read from the generated OpenAPI schema (the API key shows up as a header)."""
    out = []
    for path, operations in app.openapi()["paths"].items():
        for method, op in operations.items():
            secured = any(p.get("name", "").lower() == "x-api-key" for p in op.get("parameters", []))
            out.append({"method": method.upper(), "path": path, "summary": op.get("summary", ""),
                        "auth": secured, "tag": (op.get("tags") or [""])[0]})
    return out


@router.get("/integration/health", summary="Connection status, versions and the endpoint catalog")
def health(request: Request, db: DB) -> dict:
    try:
        db.execute(text("select 1"))
        events, last = db.execute(select(func.count(Event.id), func.max(Event.timestamp))).one()
        database = "ok"
    except SQLAlchemyError:
        events, last, database = 0, None, "error"
    return {
        "client": "NovaBank", "integration": "Identity & Risk Events API",
        "status": "CONNECTED" if database == "ok" else "DEGRADED",
        "api_health": "HEALTHY" if database == "ok" else "DEGRADED",
        "database": database, "version": __version__,
        "events_received": events, "last_event": last.isoformat() if last else None,
        "uptime_seconds": metrics.snapshot()["uptime_seconds"],
        "ai_mode": "openai" if settings.openai_api_key else "deterministic",
        "ai_model": settings.openai_model if settings.openai_api_key else None,
        "live_clients": live.hub.clients, "traffic": live.traffic.status(),
        "demo_mode": settings.demo_mode, "rate_limit_per_minute": settings.rate_limit_per_minute,
        "endpoints": endpoint_catalog(request.app),
    }


@router.get("/integration/metrics", summary="Request counts, latency percentiles and ingest throughput")
def get_metrics() -> dict:
    return {**metrics.snapshot(), "live_clients": live.hub.clients}


@router.get("/stream", summary="Server-Sent Events: live events, incidents and traffic state")
async def stream() -> StreamingResponse:
    return StreamingResponse(live.hub.stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
