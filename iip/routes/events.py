"""Event ingestion and search."""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from .. import live
from ..database import Event, User
from ..observability import metrics
from ..pipeline import process_event
from ..queries import event_dict, parse_ref
from ..schemas import EventIn
from .deps import DB, WRITE

log = logging.getLogger("iip.events")
router = APIRouter(tags=["events"])


@router.post("/events", status_code=201, dependencies=WRITE, summary="Ingest one identity / risk event")
def ingest_event(body: EventIn, db: DB) -> dict:
    try:
        event, assessment = process_event(db, body.model_dump())
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    metrics.record_ingest()
    live.broadcast(db, [event], source="api")
    out = event_dict(event)
    log.info("Ingested %s score=%s level=%s", out["event_id"], event.risk_score, event.risk_level)
    return {"event": out, "risk": assessment, "incident_id": out["incident_id"]}


@router.get("/events", summary="Search, filter and page through events")
def list_events(db: DB, q: str = "", event_type: str = "", risk_level: str = "", user_id: str = "",
                sort: Literal["asc", "desc"] = "desc", limit: int = Query(100, ge=1, le=500),
                offset: int = Query(0, ge=0)) -> dict:
    stmt = select(Event)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if risk_level:
        stmt = stmt.where(Event.risk_level == risk_level.upper())
    if user_id:
        stmt = stmt.where(Event.user_id == user_id.upper())
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Event.user_id.ilike(like), Event.ip_address.ilike(like), Event.location.ilike(like),
            Event.device_id.ilike(like), Event.resource_accessed.ilike(like),
            Event.user_id.in_(select(User.id).where(User.name.ilike(like)))))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = (Event.timestamp.asc(), Event.id.asc()) if sort == "asc" else (Event.timestamp.desc(), Event.id.desc())
    rows = db.scalars(stmt.order_by(*order).offset(offset).limit(limit))
    return {"total": total, "items": [event_dict(e) for e in rows]}


@router.get("/events/{event_id}", summary="One event with its full risk explanation")
def get_event(event_id: str, db: DB) -> dict:
    pk = parse_ref(event_id, "EVT")
    event = db.get(Event, pk) if pk else None
    if event is None:
        raise HTTPException(404, "Event not found")
    return event_dict(event)
