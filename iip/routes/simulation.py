"""Simulation Center: replay attack scenarios through the real pipeline, run live traffic, reset the demo."""
from __future__ import annotations

import random
from dataclasses import asdict
from datetime import timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from .. import live, rules
from ..clock import utcnow
from ..database import Device, Event, Incident, SessionLocal, User, reset_db
from ..observability import metrics
from ..pipeline import process_event
from ..queries import event_dict, incident_detail, incident_ref
from ..schemas import TrafficIn
from ..seed import SCENARIOS, plan_scenario, scenario_catalog, seed
from .deps import DB, WRITE

router = APIRouter(tags=["simulation"])


@router.get("/simulation", summary="Available scenarios")
def list_scenarios() -> list[dict]:
    return scenario_catalog()


# Static paths are declared before /simulation/{scenario} so they are not captured by it.
@router.get("/simulation/traffic", summary="Live traffic generator status")
def traffic_status() -> dict:
    return live.traffic.status()


@router.post("/simulation/traffic", dependencies=WRITE, summary="Start or stop the live traffic generator")
async def toggle_traffic(body: TrafficIn) -> dict:
    await (live.traffic.start() if body.enabled else live.traffic.stop())
    return live.traffic.status()


def _reseed() -> None:
    reset_db()
    with SessionLocal() as db:
        seed(db)


@router.post("/simulation/reset", dependencies=WRITE, summary="Wipe the database and re-seed fresh demo data")
async def reset_demo() -> dict:
    await live.traffic.stop()
    await run_in_threadpool(_reseed)
    live.hub.publish("reset", {"at": utcnow().isoformat()})
    return {"status": "reset", "traffic": live.traffic.status()}


BENIGN = {"baseline", "benign"}


def _settled_users(db: DB, users: list[User], idle_for: timedelta) -> tuple[list[User], list[User]]:
    """Users last seen at home and quiet for the scenario's duration, so a benign replay isn't
    contradicted by their real history (a home login two hours ago *would* make a trip impossible)."""
    ranked = select(Event.user_id, Event.location, func.row_number().over(
        partition_by=Event.user_id, order_by=Event.timestamp.desc()).label("rank")).where(
        Event.status == "success", Event.ip_reputation == "clean").subquery()
    baseline = dict(db.execute(select(ranked.c.user_id, ranked.c.location).where(ranked.c.rank == 1)).all())
    last_seen = dict(db.execute(select(Event.user_id, func.max(Event.timestamp)).group_by(Event.user_id)).all())
    settled = [u for u in users if baseline.get(u.id, u.home_location) == u.home_location]
    quiet = [u for u in settled if u.id not in last_seen or last_seen[u.id] < utcnow() - idle_for]
    return quiet, settled


def _travel_text(events: list[Event]) -> str | None:
    trip = next((e.context["travel"] for e in events if e.context.get("travel")), None)
    if not trip:
        return None
    if trip.get("distance_km") is None:
        return f"{trip['from']} → {trip['to']} in {trip['minutes']:.0f} min (distance unknown)"
    verdict = ("impossible" if trip["impossible"] else "plausible" if trip["assessed"]
               else "not judged (flagged IP or failed sign-in)")
    return (f"{trip['from']} → {trip['to']}: {trip['distance_km']:,} km in {trip['minutes']:.0f} min "
            f"≈ {trip['speed_kmh'] or 0:,} km/h · {verdict}")


@router.post("/simulation/{scenario}", dependencies=WRITE, summary="Run one scenario through the real pipeline")
def simulate(scenario: str, db: DB, user_id: str | None = None) -> dict:
    """Pass `user_id` to target one customer; otherwise a suitable customer is picked at random."""
    if scenario not in SCENARIOS:
        raise HTTPException(404, f"Unknown scenario. Valid: {', '.join(SCENARIOS)}")
    users = db.scalars(select(User)).all()
    if not users:
        raise HTTPException(409, "No users available: the database is empty")
    rnd = random.Random()
    if user_id:
        user = next((u for u in users if u.id == user_id.upper()), None)
        if user is None:
            raise HTTPException(404, "User not found")
    elif SCENARIOS[scenario].category in BENIGN:
        quiet, settled = _settled_users(db, users, idle_for=timedelta(hours=9))
        if SCENARIOS[scenario].category == "benign" and not quiet:  # a replayed trip needs a quiet customer
            cause = "live traffic is on" if live.traffic.running else "recent activity"
            raise HTTPException(409, f"No customer has been quiet for 9 hours ({cause}), so a replayed trip would "
                                     "contradict their real history. Pause live traffic or reset the demo first.")
        user = rnd.choice(quiet or settled or users)
    else:
        user = rnd.choice(users)
    device = db.scalars(select(Device.id).where(Device.user_id == user.id, Device.trusted)).first()
    if device is None:
        raise HTTPException(409, f"{user.id} has no trusted device")

    events = [process_event(db, payload)[0] for payload in plan_scenario(scenario, user, device, users, utcnow(), rnd)]
    metrics.record_ingest(len(events))
    live.broadcast(db, events, source="simulation")

    top = max(events, key=lambda e: (e.risk_score, e.timestamp))
    incident_ids = list(dict.fromkeys(e.incident_id for e in events if e.incident_id))
    primary = top.incident_id or (incident_ids[-1] if incident_ids else None)
    signals = sorted({s for e in events for s in e.signals if rules.WEIGHTS[s] > 0}, key=lambda s: -rules.WEIGHTS[s])
    affected = sorted({e.user_id for e in events})
    who = f"{user.name} ({user.id})" if len(affected) == 1 else f"{len(affected)} accounts"
    refs = ", ".join(incident_ref(i) for i in incident_ids)
    steps = [
        {"stage": "ingest", "title": "Events received",
         "detail": f"{len(events)} event(s) for {who} entered the ingestion pipeline"},
        {"stage": "normalize", "title": "Validated & normalized",
         "detail": "Schema checked, timestamps converted to UTC, city labels canonicalized"},
        {"stage": "enrich", "title": "Enriched",
         "detail": _travel_text(events) or "Device ownership, trusted travel baseline and recent history loaded"},
        {"stage": "score", "title": "Risk scored",
         "detail": f"Peak {top.risk_score}/100 ({top.risk_level}) · {', '.join(signals) or 'no risk signals'}"},
        {"stage": "correlate", "title": "Correlated",
         "detail": f"{len(incident_ids)} incident(s) opened or updated: {refs}" if incident_ids
         else f"Below the incident threshold ({rules.INCIDENT_OPEN_SCORE}): no incident"},
        {"stage": "publish", "title": "Stored & streamed",
         "detail": "Persisted to SQLite and pushed to every open dashboard over SSE"},
    ]
    return {
        "scenario": asdict(SCENARIOS[scenario]),
        "user": {"user_id": user.id, "name": user.name, "home_location": user.home_location},
        "affected_users": affected,
        "steps": steps,
        "events": [event_dict(e) for e in events],
        "top_event": event_dict(top),
        "incident": incident_detail(db, db.get(Incident, primary)) if primary else None,
        "incident_ids": [incident_ref(i) for i in incident_ids],
    }
