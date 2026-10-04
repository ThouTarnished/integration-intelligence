"""Read side: serializers plus the aggregate queries behind the dashboard, users and incidents.

List endpoints are batched (a handful of grouped queries) instead of issuing several
queries per row, so response time stays flat as the number of users/incidents grows.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from . import geo, rules
from .clock import utcnow
from .correlation import incident_title
from .database import Device, Event, Incident, RiskSignal, User

LEVEL_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


# --- identifiers ----------------------------------------------------------------------
def event_ref(pk: int) -> str:
    return f"EVT-{pk:05d}"


def incident_ref(pk: int | None) -> str | None:
    return f"INC-{pk:04d}" if pk else None


def parse_ref(value: str, prefix: str) -> int | None:
    """'EVT-00042' -> 42 when the prefix matches, else None."""
    head, _, tail = value.strip().upper().partition("-")
    return int(tail) if head == prefix and tail.isascii() and tail.isdigit() and len(tail) <= 18 else None


# --- serializers ----------------------------------------------------------------------
def event_dict(e: Event) -> dict:
    return {
        "event_id": event_ref(e.id), "user_id": e.user_id, "event_type": e.event_type,
        "timestamp": e.timestamp.isoformat(), "ip_address": e.ip_address, "location": e.location,
        "device_id": e.device_id, "device_new": e.device_new, "failed_attempts": e.failed_attempts,
        "ip_reputation": e.ip_reputation, "transaction_amount": e.transaction_amount,
        "resource_accessed": e.resource_accessed, "status": e.status,
        "risk_score": e.risk_score, "risk_level": e.risk_level, "signals": e.signals,
        "contributions": e.contributions, "context": e.context,
        "recommended_action": e.action, "explanation": e.explanation, "incident_id": incident_ref(e.incident_id),
    }


def incident_dict(i: Incident, user_name: str, event_count: int) -> dict:
    return {
        "incident_id": incident_ref(i.id), "title": incident_title(i.signals),
        "severity": i.severity, "risk_level": i.severity, "risk_score": i.risk_score, "status": i.status,
        "user_id": i.user_id, "user_name": user_name, "signals": i.signals,
        "recommended_action": i.action, "event_count": event_count,
        "created": i.created.isoformat(), "updated": i.updated.isoformat(),
    }


def incidents_page(db: Session, stmt: Select) -> list[dict]:
    """Serialize many incidents with two batched lookups (names, event counts)."""
    incidents = db.scalars(stmt).all()
    if not incidents:
        return []
    ids = [i.id for i in incidents]
    counts = dict(db.execute(
        select(Event.incident_id, func.count()).where(Event.incident_id.in_(ids)).group_by(Event.incident_id)).all())
    names = dict(db.execute(select(User.id, User.name).where(User.id.in_({i.user_id for i in incidents}))).all())
    return [incident_dict(i, names.get(i.user_id, "?"), counts.get(i.id, 0)) for i in incidents]


def incident_detail(db: Session, incident: Incident) -> dict:
    events = db.scalars(select(Event).where(Event.incident_id == incident.id).order_by(Event.timestamp)).all()
    user = db.get(User, incident.user_id)
    out = incident_dict(incident, user.name if user else "?", len(events))
    out["user"] = {"user_id": user.id, "name": user.name, "home_location": user.home_location,
                   "segment": user.segment} if user else None
    out["timeline"] = [event_dict(e) for e in events]
    out["mitre"] = list({m["id"]: m for s in incident.signals if (m := rules.SIGNALS[s].mitre)}.values())
    out["explanation"] = (f"{len(incident.signals)} distinct signals across {len(events)} correlated events: "
                          f"{', '.join(incident.signals) or 'none'}. Highest event score {incident.risk_score}/100.")
    return out


# --- users ----------------------------------------------------------------------------
def user_risk(db: Session, user_id: str) -> dict:
    """A user's current risk = their highest-risk event among the 10 most recent."""
    recent = db.scalars(select(Event).where(Event.user_id == user_id)
                        .order_by(Event.timestamp.desc()).limit(10)).all()
    if not recent:
        return {"risk_score": 0, "risk_level": "LOW", "signals": [], "recommended_action": rules.ACTIONS["LOW"],
                "explanation": "No activity recorded.", "event_id": None}
    top = max(recent, key=lambda e: (e.risk_score, e.timestamp))
    return {
        "risk_score": top.risk_score, "risk_level": top.risk_level, "signals": top.signals,
        "recommended_action": top.action, "event_id": event_ref(top.id),
        "explanation": f"Based on the highest-risk event among the user's 10 most recent "
                       f"({event_ref(top.id)}). {top.explanation}",
    }


def users_overview(db: Session) -> list[dict]:
    """Every user with current risk and activity counts, in five queries total."""
    ranked = select(
        Event.user_id, Event.risk_score, Event.risk_level, Event.timestamp,
        func.row_number().over(partition_by=Event.user_id,
                               order_by=(Event.timestamp.desc(), Event.id.desc())).label("rank"),
    ).subquery()
    top: dict[str, tuple] = {}
    for row in db.execute(select(ranked).where(ranked.c.rank <= 10)):
        best = top.get(row.user_id)
        if best is None or (row.risk_score, row.timestamp) > (best.risk_score, best.timestamp):
            top[row.user_id] = row
    activity = {uid: (n, last) for uid, n, last in db.execute(
        select(Event.user_id, func.count(), func.max(Event.timestamp)).group_by(Event.user_id))}
    incidents = dict(db.execute(select(Incident.user_id, func.count()).group_by(Incident.user_id)).all())
    open_incidents = dict(db.execute(select(Incident.user_id, func.count())
                                     .where(Incident.status != "RESOLVED").group_by(Incident.user_id)).all())
    out = []
    for u in db.scalars(select(User).order_by(User.id)):
        best = top.get(u.id)
        count, last = activity.get(u.id, (0, None))
        out.append({
            "user_id": u.id, "name": u.name, "segment": u.segment, "home_location": u.home_location,
            "risk_score": best.risk_score if best else 0, "risk_level": best.risk_level if best else "LOW",
            "event_count": count, "incident_count": incidents.get(u.id, 0),
            "open_incidents": open_incidents.get(u.id, 0), "last_activity": last.isoformat() if last else None,
        })
    return out


def user_detail(db: Session, user: User) -> dict:
    recent = db.scalars(select(Event).where(Event.user_id == user.id)
                        .order_by(Event.timestamp.desc()).limit(40)).all()
    locations = db.execute(select(Event.location, func.count()).where(Event.user_id == user.id)
                           .group_by(Event.location).order_by(func.count().desc())).all()
    device_use = dict(db.execute(select(Event.device_id, func.count()).where(Event.user_id == user.id)
                                 .group_by(Event.device_id)).all())
    devices = db.scalars(select(Device).where(Device.user_id == user.id).order_by(Device.id)).all()
    return {
        "user_id": user.id, "name": user.name, "segment": user.segment, "home_location": user.home_location,
        "risk": user_risk(db, user.id),
        "devices": [{"device_id": d.id, "trusted": d.trusted, "events": device_use.get(d.id, 0)} for d in devices],
        "locations": [{"location": loc, "events": n, "home": loc == user.home_location} for loc, n in locations],
        "risk_history": [{"timestamp": e.timestamp.isoformat(), "risk_score": e.risk_score,
                          "risk_level": e.risk_level, "event_id": event_ref(e.id)} for e in reversed(recent[:30])],
        "timeline": [event_dict(e) for e in reversed(recent[:15])],
        "incidents": incidents_page(db, select(Incident).where(Incident.user_id == user.id)
                                    .order_by(Incident.updated.desc())),
    }


# --- geography ------------------------------------------------------------------------
def geo_overview(db: Session, arc_limit: int = 40) -> dict:
    """Cities with activity (for map markers) and recent city-to-city trips (for arcs)."""
    homes = Counter(home for (home,) in db.execute(select(User.home_location)))
    cities = []
    for location, events, max_risk in db.execute(
            select(Event.location, func.count(), func.max(Event.risk_score)).group_by(Event.location)):
        if point := geo.coords(location):
            cities.append({"name": location, "lat": point[0], "lon": point[1], "events": events,
                           "max_risk": max_risk, "level": rules.classify(max_risk), "home_users": homes[location]})
    arcs = []
    rows = db.execute(select(Event.id, Event.timestamp, Event.risk_level, Event.context)
                      .order_by(Event.timestamp.desc()).limit(800))
    for pk, ts, level, context in rows:
        trip = (context or {}).get("travel")
        if not trip or not (a := geo.coords(trip["from"])) or not (b := geo.coords(trip["to"])):
            continue
        arcs.append({"event_id": event_ref(pk), "timestamp": ts.isoformat(), "risk_level": level,
                     "impossible": trip.get("impossible", False), "assessed": trip.get("assessed", True),
                     "speed_kmh": trip.get("speed_kmh"),
                     "distance_km": trip.get("distance_km"), "minutes": trip.get("minutes"),
                     "from": {"name": trip["from"], "lat": a[0], "lon": a[1]},
                     "to": {"name": trip["to"], "lat": b[0], "lon": b[1]}})
        if len(arcs) >= arc_limit:
            break
    return {"cities": cities, "arcs": arcs}


# --- dashboard ------------------------------------------------------------------------
def dashboard_summary(db: Session) -> dict:
    now = utcnow()
    days = [now.date() - timedelta(days=k) for k in range(6, -1, -1)]
    per_day = {d: Counter() for d in days}
    day = func.date(Event.timestamp)
    for d, level, n in db.execute(select(day, Event.risk_level, func.count())
                                  .where(Event.timestamp >= datetime.combine(days[0], time.min))
                                  .group_by(day, Event.risk_level)):
        if (key := date.fromisoformat(str(d))) in per_day:
            per_day[key][level] += n
    per_hour = [{"total": 0, "risky": 0} for _ in range(24)]
    for ts, level in db.execute(select(Event.timestamp, Event.risk_level)
                                .where(Event.timestamp > now - timedelta(hours=24))):
        hours_ago = int((now - ts).total_seconds() // 3600)
        if 0 <= hours_ago < 24:
            per_hour[23 - hours_ago]["total"] += 1
            per_hour[23 - hours_ago]["risky"] += level in ("HIGH", "CRITICAL")

    levels = dict(db.execute(select(Event.risk_level, func.count()).group_by(Event.risk_level)).all())
    statuses = dict(db.execute(select(Incident.status, func.count()).group_by(Incident.status)).all())
    severities = db.execute(select(Incident.severity, func.count()).group_by(Incident.severity)
                            .order_by(func.count().desc())).all()
    active = select(func.count()).select_from(Incident).where(Incident.status != "RESOLVED")
    last_24h = select(func.count()).select_from(Event).where(Event.timestamp >= now - timedelta(hours=24))
    prev_24h = select(func.count()).select_from(Event).where(
        Event.timestamp >= now - timedelta(hours=48), Event.timestamp < now - timedelta(hours=24))
    signal_counts = db.execute(select(RiskSignal.name, func.count()).where(RiskSignal.weight > 0)
                               .group_by(RiskSignal.name).order_by(func.count().desc()).limit(8))
    scores = dict(db.execute(select(Event.risk_score, func.count()).group_by(Event.risk_score)).all())
    return {
        "generated_at": now.isoformat(),
        "total_events": sum(levels.values()),
        "events_24h": db.scalar(last_24h),
        "events_prev_24h": db.scalar(prev_24h),
        "active_incidents": db.scalar(active),
        "critical_incidents": db.scalar(active.where(Incident.severity == "CRITICAL")),
        "high_risk_events": levels.get("HIGH", 0) + levels.get("CRITICAL", 0),
        "incident_status": {s: statuses.get(s, 0) for s in ("OPEN", "INVESTIGATING", "RESOLVED")},
        "events_by_day": [{"date": d.isoformat(), "label": d.strftime("%a"), "total": sum(c.values()),
                           **{lvl: c[lvl] for lvl in LEVEL_ORDER}} for d, c in per_day.items()],
        "events_by_hour": per_hour,
        "score_histogram": [{"score": s, "value": scores.get(s, 0), "level": rules.classify(s)}
                            for s in range(0, 101, 5)],
        "incident_severity": [{"label": label, "value": n} for label, n in severities],
        "top_signals": [{"label": name, "value": n, "weight": rules.WEIGHTS[name], "mitre": rules.SIGNALS[name].mitre}
                        for name, n in signal_counts],
        "recent_incidents": incidents_page(db, select(Incident).order_by(Incident.updated.desc()).limit(6)),
        "recent_events": [event_dict(e) for e in db.scalars(select(Event).order_by(Event.timestamp.desc()).limit(12))],
        "top_users": sorted(users_overview(db), key=lambda u: (-u["risk_score"], u["user_id"]))[:6],
        "geo": geo_overview(db),
    }
