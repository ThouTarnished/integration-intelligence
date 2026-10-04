"""Incident queue and triage."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from .. import live
from ..database import Incident
from ..queries import incident_detail, incidents_page, parse_ref
from ..schemas import StatusIn
from .deps import DB, WRITE

router = APIRouter(tags=["incidents"])


def _incident_or_404(db: DB, incident_id: str) -> Incident:
    pk = parse_ref(incident_id, "INC")
    incident = db.get(Incident, pk) if pk else None
    if incident is None:
        raise HTTPException(404, "Incident not found")
    return incident


@router.get("/incidents", summary="Incidents, most recently active first")
def list_incidents(db: DB, status: str = "", limit: int = 200) -> list[dict]:
    stmt = select(Incident)
    if status:
        stmt = stmt.where(Incident.status == status.upper())
    return incidents_page(db, stmt.order_by(Incident.updated.desc()).limit(min(max(limit, 1), 500)))


@router.get("/incidents/{incident_id}", summary="Incident with correlated timeline and ATT&CK context")
def get_incident(incident_id: str, db: DB) -> dict:
    return incident_detail(db, _incident_or_404(db, incident_id))


@router.patch("/incidents/{incident_id}", dependencies=WRITE, summary="Move an incident through triage")
def set_status(incident_id: str, body: StatusIn, db: DB) -> dict:
    incident = _incident_or_404(db, incident_id)
    incident.status = body.status
    db.commit()
    detail = incident_detail(db, incident)
    live.hub.publish("incident", {k: v for k, v in detail.items() if k not in ("timeline", "user", "mitre")})
    return detail
