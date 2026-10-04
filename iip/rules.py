"""The risk rulebook: every signal the engine can raise, its weight, and how scores become decisions.

Weights and thresholds are fictional demo logic chosen to be easy to reason about. They
are NOT a real-world security standard, although the travel and spray thresholds follow
public vendor guidance (Panther, Datadog, Elastic, Microsoft Entra). This module is pure
(no database, no I/O): the engine stays trivially unit-testable and the Risk Lab runs
what-if analysis against exactly the same code the ingestion pipeline uses.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import geo


@dataclass(frozen=True)
class Signal:
    name: str
    weight: int
    description: str
    mitre_id: str | None = None
    mitre_name: str | None = None

    @property
    def mitre(self) -> dict | None:
        """MITRE ATT&CK technique this signal is indicative of (context, not proof)."""
        if not self.mitre_id:
            return None
        path = self.mitre_id.replace(".", "/")
        return {"id": self.mitre_id, "name": self.mitre_name, "url": f"https://attack.mitre.org/techniques/{path}/"}

    def as_dict(self) -> dict:
        return {"name": self.name, "weight": self.weight, "description": self.description, "mitre": self.mitre}


SIGNALS: dict[str, Signal] = {s.name: s for s in (
    Signal("Impossible travel", 40,
           "Reaching this city from the last trusted sign-in would need a faster-than-airliner speed.",
           "T1078", "Valid Accounts"),
    Signal("Suspicious IP", 30, "Source IP carries a suspicious or malicious reputation.", "T1090", "Proxy"),
    Signal("Suspicious transaction", 30, "Very large transfer, or a mid-size one from a risky context.",
           "T1657", "Financial Theft"),
    Signal("Password spray", 25, "Many different accounts failing to sign in from the same IP.",
           "T1110.003", "Password Spraying"),
    Signal("Unusual location", 20, "Activity outside the user's home city.", "T1078", "Valid Accounts"),
    Signal("Multiple failed login attempts", 20, "Three or more failed attempts reported on the event.",
           "T1110.001", "Password Guessing"),
    Signal("Rapid transactions", 20, "Three or more transactions inside ten minutes (card-testing velocity).",
           "T1657", "Financial Theft"),
    Signal("New device", 15, "Device never seen for this user.", "T1078", "Valid Accounts"),
    Signal("Password reset after failures", 15, "Password reset shortly after repeated failed logins.",
           "T1098", "Account Manipulation"),
    Signal("Privileged resource access", 10, "Access to an admin console, wire approvals or bulk customer data.",
           "T1078", "Valid Accounts"),
    Signal("Trusted device", -15, "Known, trusted device for this user (reduces risk)."),
)}
WEIGHTS: dict[str, int] = {name: signal.weight for name, signal in SIGNALS.items()}

# --- detection thresholds -------------------------------------------------------------
FAILED_ATTEMPTS_THRESHOLD = 3
LARGE_TRANSACTION = 10_000
RISKY_CONTEXT_TRANSACTION = 2_000
RAPID_TRANSACTION_WINDOW = timedelta(minutes=10)
RAPID_TRANSACTION_COUNT = 3
RESET_LOOKBACK = timedelta(hours=1)
RESET_FAILURES = 3
SPRAY_WINDOW = timedelta(minutes=30)
SPRAY_ACCOUNTS = 5                  # distinct accounts failing from one IP
IMPOSSIBLE_SPEED_KMH = 900          # a commercial airliner's cruise speed (Panther uses the same figure)
MIN_TRAVEL_KM = 500                 # shorter hops are within geo-IP noise (Datadog / Elastic)
UNKNOWN_CITY_WINDOW = timedelta(hours=2)
PRIVILEGED_RESOURCES = frozenset({"admin-console", "wire-approval", "customer-pii-export"})

# --- decisions ------------------------------------------------------------------------
LEVELS = (("CRITICAL", 80), ("HIGH", 60), ("MEDIUM", 30), ("LOW", 0))
ACTIONS = {
    "LOW": "Allow",
    "MEDIUM": "Monitor and log",
    "HIGH": "Require step-up authentication",
    "CRITICAL": "Block session and require additional verification",
}

# --- incident correlation -------------------------------------------------------------
CORRELATION_WINDOW = timedelta(minutes=30)
INCIDENT_OPEN_SCORE = 60   # an event this risky opens a new incident
INCIDENT_JOIN_SCORE = 30   # an event this risky joins an incident that is already open
INCIDENT_PULL_SCORE = 20   # preceding events this risky (or failed) are pulled into a new incident


@dataclass(frozen=True)
class History:
    """What the pipeline knows *before* the event being scored."""

    home_location: str
    trusted_device: bool
    baseline_location: str | None = None      # last successful, clean-IP event (trustworthy geo)
    baseline_timestamp: datetime | None = None
    recent_transactions: int = 0              # this user's transactions inside RAPID_TRANSACTION_WINDOW
    recent_failures: int = 0                  # this user's failed logins inside RESET_LOOKBACK
    spray_accounts: int = 0                   # *other* accounts failing from this IP inside SPRAY_WINDOW


@dataclass(frozen=True)
class Finding:
    signal: str
    detail: str


def minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def classify(score: int) -> str:
    return next(level for level, floor in LEVELS if score >= floor)


def compute_score(signals: Iterable[str]) -> int:
    return max(0, min(100, sum(WEIGHTS[name] for name in signals)))


def impossible_travel(trip: geo.Travel) -> str | None:
    """Explain why a trip is physically implausible, or return None if it is fine."""
    if trip.distance_km is None:  # unknown city: fall back to the simple time-window heuristic
        if trip.minutes <= minutes(UNKNOWN_CITY_WINDOW):
            return f"{trip.origin} → {trip.destination} within {trip.minutes:.0f} min (distance unknown)"
        return None
    if trip.distance_km >= MIN_TRAVEL_KM and trip.speed_kmh > IMPOSSIBLE_SPEED_KMH:
        return (f"{trip.origin} → {trip.destination}: {trip.distance_km:,.0f} km in {trip.minutes:.0f} min "
                f"≈ {trip.speed_kmh:,.0f} km/h")
    return None


def detect(event: dict, history: History) -> tuple[list[Finding], dict]:
    """Run every rule against one normalized event. Returns findings plus enrichment context."""
    findings: list[Finding] = []
    context: dict = {}
    failed = event["status"] == "failure"
    clean_ip = event["ip_reputation"] == "clean"

    def flag(signal: str, detail: str) -> None:
        findings.append(Finding(signal, detail))

    if event["device_new"]:
        flag("New device", f"{event['device_id']} has never been seen for this user")
    if event["location"] != history.home_location:
        flag("Unusual location", f"{event['location']} (home: {history.home_location})")
    if not clean_ip:
        flag("Suspicious IP", f"{event['ip_address']} is reported {event['ip_reputation']}")
    if event["failed_attempts"] >= FAILED_ATTEMPTS_THRESHOLD:
        flag("Multiple failed login attempts", f"{event['failed_attempts']} failed attempts")
    if failed and history.spray_accounts + 1 >= SPRAY_ACCOUNTS:
        flag("Password spray", f"{history.spray_accounts + 1} accounts failed from {event['ip_address']} "
                               f"within {minutes(SPRAY_WINDOW)} minutes")

    # Travel is computed for every move (it feeds the map) but only *judged* on successful,
    # clean-IP events: proxies and VPN exits make geolocation unreliable, so a flagged IP
    # is scored by "Suspicious IP" instead (the approach Panther and Defender take).
    if history.baseline_location and history.baseline_location != event["location"]:
        trip = geo.travel_between(history.baseline_location, history.baseline_timestamp,
                                  event["location"], event["timestamp"])
        assessed = not failed and clean_ip
        verdict = impossible_travel(trip) if assessed else None
        context["travel"] = {**trip.as_dict(), "assessed": assessed, "impossible": verdict is not None}
        if verdict:
            flag("Impossible travel", verdict)

    if event["event_type"] == "transaction":
        amount = event.get("transaction_amount") or 0
        risky_context = event["device_new"] or not clean_ip
        if amount >= LARGE_TRANSACTION:
            flag("Suspicious transaction", f"${amount:,.2f} exceeds the ${LARGE_TRANSACTION:,} review threshold")
        elif amount >= RISKY_CONTEXT_TRANSACTION and risky_context:
            flag("Suspicious transaction", f"${amount:,.2f} from a new device or flagged IP")
        if history.recent_transactions + 1 >= RAPID_TRANSACTION_COUNT:
            flag("Rapid transactions", f"{history.recent_transactions + 1} transactions within "
                                       f"{minutes(RAPID_TRANSACTION_WINDOW)} minutes")

    if event["event_type"] == "password_reset" and history.recent_failures >= RESET_FAILURES:
        flag("Password reset after failures", f"{history.recent_failures} failed logins in the previous hour")
    if event.get("resource_accessed") in PRIVILEGED_RESOURCES:
        flag("Privileged resource access", f"accessed {event['resource_accessed']}")
    if history.trusted_device and not event["device_new"]:
        flag("Trusted device", f"{event['device_id']} is trusted for this user")
    return findings, context


def assess(findings: list[Finding]) -> dict:
    """Turn findings into a scored, explained decision (heaviest contributions first)."""
    ordered = sorted(findings, key=lambda f: -WEIGHTS[f.signal])
    signals = [f.signal for f in ordered]
    score = compute_score(signals)
    level = classify(score)
    risky = [s for s in signals if WEIGHTS[s] > 0]
    if risky:
        explanation = (f"Signals deviating from this user's baseline: {', '.join(risky)}. "
                       f"Rule-based score {score}/100 ({level}).")
    else:
        explanation = "No risk signals detected; activity matches the user's baseline."
    return {
        "risk_score": score,
        "risk_level": level,
        "signals": signals,
        "contributions": [{"signal": f.signal, "weight": WEIGHTS[f.signal], "detail": f.detail,
                           "mitre": SIGNALS[f.signal].mitre} for f in ordered],
        "recommended_action": ACTIONS[level],
        "explanation": explanation,
    }


def what_if(signal_names: Iterable[str]) -> dict:
    """Score a hand-picked set of signals (Risk Lab). Unknown names raise KeyError."""
    return assess([Finding(name, SIGNALS[name].description) for name in dict.fromkeys(signal_names)])


def rulebook() -> dict:
    """Everything a client needs to render the rules: signals, levels, actions and thresholds."""
    return {
        "signals": [s.as_dict() for s in SIGNALS.values()],
        "levels": [{"level": level, "min_score": floor, "action": ACTIONS[level]} for level, floor in reversed(LEVELS)],
        "thresholds": {
            "failed_attempts": FAILED_ATTEMPTS_THRESHOLD,
            "large_transaction": LARGE_TRANSACTION,
            "risky_context_transaction": RISKY_CONTEXT_TRANSACTION,
            "rapid_transactions": {"count": RAPID_TRANSACTION_COUNT,
                                   "window_minutes": minutes(RAPID_TRANSACTION_WINDOW)},
            "password_spray": {"accounts": SPRAY_ACCOUNTS, "window_minutes": minutes(SPRAY_WINDOW)},
            "impossible_travel": {"speed_kmh": IMPOSSIBLE_SPEED_KMH, "min_distance_km": MIN_TRAVEL_KM},
            "incident": {"open": INCIDENT_OPEN_SCORE, "join": INCIDENT_JOIN_SCORE,
                         "window_minutes": minutes(CORRELATION_WINDOW)},
        },
        "privileged_resources": sorted(PRIVILEGED_RESOURCES),
    }
