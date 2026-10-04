"""Write path for one event: normalize -> enrich -> score -> persist -> correlate.

Every ingestion channel (REST API, Simulation Center, live-traffic generator, seeder)
goes through `process_event`, so all events are scored by exactly the same rules.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import geo, rules
from .clock import utcnow
from .correlation import correlate
from .database import Device, Event, RiskSignal, User


def normalize(payload: dict) -> dict:
    """Canonical shape: UTC timestamp, canonical city label, trimmed strings."""
    data = dict(payload)
    data["timestamp"] = data.get("timestamp") or utcnow()
    data["location"] = geo.canonical(data["location"])
    data["ip_address"] = data["ip_address"].strip()
    data.setdefault("failed_attempts", 0)
    data.setdefault("ip_reputation", "clean")
    data.setdefault("status", "success")
    if data.get("resource_accessed"):
        data["resource_accessed"] = data["resource_accessed"].strip().lower()
    return data


def load_history(db: Session, user: User, data: dict, trusted: bool) -> rules.History:
    """Everything the rules need to know about activity before this event."""
    ts = data["timestamp"]

    def count(*conditions, column=Event.id, window) -> int:
        stmt = select(func.count(func.distinct(column))).where(Event.timestamp < ts, Event.timestamp >= ts - window)
        return db.scalar(stmt.where(*conditions)) or 0

    # The travel baseline is the last event we can trust geographically.
    baseline = db.scalars(
        select(Event).where(Event.user_id == user.id, Event.timestamp < ts, Event.status == "success",
                            Event.ip_reputation == "clean").order_by(Event.timestamp.desc()).limit(1)).first()
    return rules.History(
        home_location=user.home_location,
        trusted_device=trusted,
        baseline_location=baseline.location if baseline else None,
        baseline_timestamp=baseline.timestamp if baseline else None,
        recent_transactions=count(Event.user_id == user.id, Event.event_type == "transaction",
                                  window=rules.RAPID_TRANSACTION_WINDOW),
        recent_failures=count(Event.user_id == user.id, Event.status == "failure", window=rules.RESET_LOOKBACK),
        spray_accounts=count(Event.ip_address == data["ip_address"], Event.status == "failure",
                             Event.user_id != user.id, column=Event.user_id, window=rules.SPRAY_WINDOW),
    )


def process_event(db: Session, payload: dict, *, commit: bool = True) -> tuple[Event, dict]:
    user = db.get(User, payload["user_id"])
    if user is None:
        raise LookupError(f"Unknown user {payload['user_id']}")
    data = normalize(payload)

    # Enrich: is this device known, and does it belong to this user?
    device = db.get(Device, data["device_id"])
    owned = device is not None and device.user_id == user.id
    if data.get("device_new") is None:
        data["device_new"] = not owned
    if device is None:
        db.add(Device(id=data["device_id"], user_id=user.id, trusted=False))
    history = load_history(db, user, data, trusted=owned and device.trusted)

    # Score with the pure rulebook.
    findings, context = rules.detect(data, history)
    assessment = rules.assess(findings)

    event = Event(
        user_id=user.id, event_type=data["event_type"], timestamp=data["timestamp"],
        ip_address=data["ip_address"], location=data["location"], device_id=data["device_id"],
        device_new=data["device_new"], failed_attempts=data["failed_attempts"],
        ip_reputation=data["ip_reputation"], transaction_amount=data.get("transaction_amount"),
        resource_accessed=data.get("resource_accessed"), status=data["status"],
        risk_score=assessment["risk_score"], risk_level=assessment["risk_level"],
        signals=assessment["signals"], contributions=assessment["contributions"], context=context,
        action=assessment["recommended_action"], explanation=assessment["explanation"],
    )
    db.add(event)
    db.flush()  # assigns event.id
    db.add_all(RiskSignal(event_id=event.id, name=s, weight=rules.WEIGHTS[s]) for s in assessment["signals"])
    correlate(db, event)
    if commit:
        db.commit()
    return event, assessment
