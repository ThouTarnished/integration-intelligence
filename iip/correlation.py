"""Incident correlation: group a user's related risky events into one investigation.

* An event scoring >= INCIDENT_JOIN_SCORE joins the user's open incident if that incident
  was active within the correlation window.
* Otherwise an event scoring >= INCIDENT_OPEN_SCORE opens a new incident and pulls in the
  user's preceding suspicious or failed events from the same window.
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import rules
from .database import Event, Incident

# First matching rule names the incident; order matters (most specific first).
_PATTERNS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"Multiple failed login attempts", "Privileged resource access"}), "Account takeover"),
    (frozenset({"Multiple failed login attempts", "Suspicious transaction"}), "Account takeover"),
    (frozenset({"Password spray"}), "Password spray"),
    (frozenset({"Password reset after failures"}), "Account recovery abuse"),
    (frozenset({"Rapid transactions"}), "Card testing"),
    (frozenset({"Impossible travel"}), "Impossible travel"),
    (frozenset({"Suspicious transaction"}), "Transaction fraud"),
    (frozenset({"Multiple failed login attempts"}), "Credential attack"),
    (frozenset({"New device", "Unusual location"}), "Unfamiliar sign-in"),
)


def incident_title(signals: list[str]) -> str:
    present = set(signals)
    return next((title for required, title in _PATTERNS if required <= present), "Anomalous activity")


def pattern_signals(title: str) -> list[list[str]]:
    """The signal combinations that earn an incident this title (quoted by the AI analyst)."""
    return [sorted(required) for required, name in _PATTERNS if name == title]


def correlate(db: Session, event: Event) -> None:
    if event.risk_score < rules.INCIDENT_JOIN_SCORE:
        return
    window_start, window_end = event.timestamp - rules.CORRELATION_WINDOW, event.timestamp + rules.CORRELATION_WINDOW
    incident = db.scalars(
        select(Incident)
        .where(Incident.user_id == event.user_id, Incident.status != "RESOLVED",
               Incident.updated >= window_start, Incident.created <= window_end)
        .order_by(Incident.updated.desc())
        .limit(1)
    ).first()

    if incident is None:
        if event.risk_score < rules.INCIDENT_OPEN_SCORE:
            return
        incident = Incident(user_id=event.user_id, status="OPEN", created=event.timestamp, updated=event.timestamp)
        db.add(incident)
        db.flush()
        preceding = db.scalars(select(Event).where(
            Event.user_id == event.user_id, Event.timestamp.between(window_start, event.timestamp),
            Event.incident_id.is_(None), or_(Event.risk_score >= rules.INCIDENT_PULL_SCORE, Event.status == "failure")))
        for earlier in preceding:
            earlier.incident_id = incident.id

    event.incident_id = incident.id
    db.flush()
    refresh_incident(db, incident)


def refresh_incident(db: Session, incident: Incident) -> None:
    """Recompute an incident's score, severity, signals and action from its events."""
    events = db.scalars(select(Event).where(Event.incident_id == incident.id).order_by(Event.timestamp)).all()
    signals: list[str] = []
    for ev in events:
        signals += [s for s in ev.signals if rules.WEIGHTS[s] > 0 and s not in signals]
    incident.risk_score = max(ev.risk_score for ev in events)
    incident.severity = rules.classify(incident.risk_score)
    incident.signals = signals
    incident.action = rules.ACTIONS[incident.severity]
    incident.updated = max(ev.timestamp for ev in events)
