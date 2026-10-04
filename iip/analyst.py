"""AI Analyst: answers questions about the platform's records and explains the risk engine's decisions.

The rule engine decides; the analyst only explains. A question is first parsed into explicit search terms (record
IDs, a customer, signals, attack patterns, places, risk levels, statuses, event types, an outcome and a time window)
by plain rules, and only the records matching those terms are pulled from the database. With OPENAI_API_KEY set, the
question plus that context is sent to an OpenAI-compatible chat API. Otherwise (or on any API error) a deterministic
analyst composes the answer from exactly the same context, so the feature works offline and is fully testable.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta

import httpx
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from . import geo, rules
from .clock import utcnow
from .config import settings
from .correlation import incident_title, pattern_signals
from .database import Event, Incident, RiskSignal, User
from .queries import (
    LEVEL_ORDER,
    event_dict,
    event_ref,
    incident_detail,
    incident_ref,
    incidents_page,
    user_risk,
    users_overview,
)

log = logging.getLogger("iip.analyst")

SYSTEM_PROMPT = (
    "You are a security analyst assistant for a bank's identity-risk platform. Answer ONLY from the JSON "
    "context, which holds how the question was interpreted and the matching records. Risk scores come from a "
    "deterministic rule engine: explain them, never change them. Be concise (under ~140 words); short markdown "
    "bullet points and **bold** are welcome. Quote IDs such as INC-0001, EVT-00001 or USR-1001 exactly as given."
)
LIST_LIMIT = 8  # records listed per answer; totals are always exact

# --- vocabulary: regexes over the normalized question (lower case, no accents) --------------------------------
_NOT_A_DURATION = r"(?!\s*(?:h|hrs?|hours?|mins?|minutes?|days?)\b)"  # "incident 3" yes, "event 24 hours" no
INCIDENT_REF = re.compile(r"\b(?:inc|incident)\s*[-#:]?\s*0*(\d{1,6})\b" + _NOT_A_DURATION)
EVENT_REF = re.compile(r"\b(?:evt|event)\s*[-#:]?\s*0*(\d{1,7})\b" + _NOT_A_DURATION)
USER_REF = re.compile(r"\b(?:usr|user|customer)\s*[-#:]?\s*(\d{4,6})\b")

# Hyphens become spaces before these are matched, so "sign-in", "sign in" and "signin" all read the same.
PATTERN_PHRASES = {  # incident titles that need several signals together (see correlation.py)
    "Account takeover": r"\baccount takeovers?\b|\bato\b|\btaken over\b",
    "Unfamiliar sign-in": r"\bunfamiliar sign ?ins?\b",
}
SIGNAL_PHRASES = {
    "Impossible travel": r"\bimpossible trav\w*|\bgeo ?velocity\b",
    "Suspicious IP": r"\b(?:suspicious|malicious|bad|risky|flagged) ip(?: address(?:es)?)?s?\b|\bip reputation\b"
                     r"|\bprox(?:y|ies)\b|\btor\b",
    "Suspicious transaction": r"\b(?:suspicious|large|big|huge|fraudulent) (?:transaction|transfer|payment)s?\b"
                              r"|\bhigh value\b|\btransaction fraud\b",
    "Password spray": r"\bspray\w*",
    "Unusual location": r"\bunusual locations?\b|\babroad\b|\baway from home\b|\boutside (?:their |the )?home\b",
    "Multiple failed login attempts": r"\bbrute ?forc\w*|\bfailed (?:login |sign ?in )?attempts\b"
                                      r"|\bpassword guessing\b|\bcredential (?:attacks?|stuffing)\b"
                                      r"|\bmultiple failed\b",
    "Rapid transactions": r"\brapid transactions?\b|\bcard testing\b|\btransaction velocity\b",
    "New device": r"\b(?:new|unknown|unrecogni[sz]ed|unfamiliar) devices?\b",
    "Password reset after failures": r"\b(?:reset|recovery) abuse\b|\baccount recovery\b|\breset after fail\w*",
    "Privileged resource access": r"\bprivileged\b|\badmin(?:istrator)? (?:console|access)\b|\bwire approvals?\b"
                                  r"|\bpii export\b",
    "Trusted device": r"\btrusted devices?\b",
}
LEVEL_PHRASES = (
    (("CRITICAL",), r"\bcritical\b"),
    (("HIGH", "CRITICAL"), r"\bhigh(?: (?:risk|severity|priority))?\b"),
    (("MEDIUM",), r"\b(?:medium|moderate)(?: (?:risk|severity))?\b"),
    (("LOW",), r"\blow(?: (?:risk|severity))?\b"),
)
FLAGGED = r"\b(?:flagged|suspicious|risky|dangerous|unusual|anomal\w*)\b"  # vague risk words: MEDIUM or above
STATUS_PHRASES = (
    (("RESOLVED",), r"\b(?:resolved|closed)\b"),
    (("INVESTIGATING",), r"\binvestigating\b|\bunder investigation\b|\bbeing investigated\b"),
    (("INVESTIGATING", "OPEN"),
     r"\b(?:open|unresolved|outstanding|pending|ongoing)\b|\bactive (?:incidents?|cases?)\b"),
)
EVENT_TYPE_PHRASES = {
    "login": r"\blog ?ins?\b|\blogged in\b|\bsign ?ins?\b|\bsigned in\b",
    "transaction": r"\btransactions?\b|\bpayments?\b|\btransfers?\b|\bpurchases?\b",
    "password_reset": r"\bpassword resets?\b|\breset (?:their |the |a )?passwords?\b",
    "resource_access": r"\bresource access\w*|\baccessed\b",
}
OUTCOME_PHRASES = (
    ("failure", r"\bfail(?:ed|ing|ures?|s)?\b|\bunsuccessful\b|\bdenied\b|\brejected\b"),
    ("success", r"\bsuccessful(?:ly)?\b|\bsucceeded\b"),
)
SUBJECTS = (  # what to list; the first match wins
    ("customers", r"\b(?:customers?|users?|people|clients?|who|whom|whose)\b|\baccounts?\b(?! (?:takeover|recovery))"),
    ("incidents", r"\b(?:incidents?|cases?|alerts?|attacks?|threats?)\b"),
    ("events", r"\b(?:events?|activit(?:y|ies))\b|" + "|".join(EVENT_TYPE_PHRASES.values())),
)
TOP_INCIDENT = r"\bthis (?:incident|case|alert|one|risk score|score)\b" \
               r"|\b(?:top|worst|most urgent|most critical|riskiest|highest risk) (?:incident|case|alert)\b"
TOP_CUSTOMER = r"\b(?:riskiest|most risky|highest risk|most dangerous|worst)\b(?: \w+)? (?:customer|user|person)\b"
SCORING = r"\b(?:how|what)\b.*\b(?:scor(?:e|es|ed|ing)|risk levels?|weights?)\b" \
          r"|\b(?:scor(?:e|es|ing)|risk levels?|weights?)\b.*\b(?:work|calculated|computed|mean)\b"
DEFINE = r"^(?:what|whats|what's) (?:is|are|does|do|was)\b|\bdefin\w*|\bmean(?:s|ing)?\b|^(?:explain|describe)\b" \
         r"|\bhow does\b.*\bwork\b|\btell me about\b"
LISTING = r"\b(?:show|list|find|which|any|display|search|who)\b"
COUNT = r"\bhow many\b|\bnumber of\b|\bcount\b"
SUMMARY = r"\bsummar\w*|\boverview\b|\brecap\b|\bbrief\w*|\bwhat'?s (?:going on|happening|new)\b|\bwhat happened\b" \
          r"|\bstatus report\b|\bsituation\b"
RECENT = r"\b(?:latest|newest|most recent|recent(?:ly)?)\b"

# Exact trigger conditions, quoted from the rulebook when a signal is defined.
TRIGGERS = {
    "Impossible travel": f"It fires above {rules.IMPOSSIBLE_SPEED_KMH} km/h over at least {rules.MIN_TRAVEL_KM} km, "
                         "measured from the last trusted sign-in and judged only on successful, clean-IP events.",
    "Password spray": f"It fires when {rules.SPRAY_ACCOUNTS}+ accounts fail from one IP within "
                      f"{rules.minutes(rules.SPRAY_WINDOW)} minutes.",
    "Suspicious transaction": f"It fires at ${rules.LARGE_TRANSACTION:,}+, or ${rules.RISKY_CONTEXT_TRANSACTION:,}+ "
                              "from a new device or flagged IP.",
    "Rapid transactions": f"It fires on {rules.RAPID_TRANSACTION_COUNT}+ transactions within "
                          f"{rules.minutes(rules.RAPID_TRANSACTION_WINDOW)} minutes.",
    "Multiple failed login attempts": f"It fires when an event reports {rules.FAILED_ATTEMPTS_THRESHOLD}+ failed "
                                      "attempts.",
    "Password reset after failures": f"It fires on a reset after {rules.RESET_FAILURES}+ failed logins in the "
                                     f"previous {rules.minutes(rules.RESET_LOOKBACK)} minutes.",
    "Privileged resource access": f"It fires on access to {', '.join(sorted(rules.PRIVILEGED_RESOURCES))}.",
}
IMPLIED_TYPES = {"Suspicious transaction": "transaction", "Rapid transactions": "transaction",
                 "Password reset after failures": "password_reset", "Privileged resource access": "resource_access"}


def _normalize(text: str) -> str:
    """Lower case, curly quotes made straight, accents dropped ("São Paulo" -> "sao paulo"), spaces collapsed."""
    text = unicodedata.normalize("NFKD", text.replace("\u2019", "'")).encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


def _places() -> list[tuple[str, tuple[str, ...]]]:
    """Every way a question can name a known city: "lagos" or "nigeria" -> Lagos, "uae" -> Abu Dhabi and Dubai."""
    names: dict[str, list[str]] = {}
    for label in geo.CITIES:
        for part in label.split(", "):
            names.setdefault(_normalize(part), []).append(label)
    # Country aliases come from geo.py; "us" is left out because in a question it is usually the pronoun.
    names |= {alias: names[country] for alias, country in geo.COUNTRY_ALIASES.items() if alias != "us"}
    # Longest first, so "new york" is taken before a shorter name inside it could be.
    ordered = sorted(names.items(), key=lambda kv: -len(kv[0]))
    return [(rf"\b{re.escape(name)}\b", tuple(labels)) for name, labels in ordered]


PLACES = _places()
USA = tuple(label for label in geo.CITIES if label.endswith(", USA"))


@dataclass
class Question:
    """What a question asks for, read with plain rules: no model is involved in deciding what to retrieve."""
    text: str
    intent: str = "list"  # focus | top | scoring | define | count | summary | list
    subject: str | None = None  # incidents | events | customers
    incident_id: int | None = None
    event_id: int | None = None
    user_id: str | None = None
    signals: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    levels: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    outcome: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    window: str | None = None
    recent: bool = False
    one: bool = False  # asks for the single riskiest customer
    not_found: list[str] = field(default_factory=list)

    @property
    def filtered(self) -> bool:
        return bool(self.signals or self.patterns or self.places or self.levels or self.statuses
                    or self.event_types or self.outcome or self.since)

    def summary(self) -> dict:
        """How the question was understood: given to the model and used to phrase the answer."""
        out = {k: v for k, v in asdict(self).items() if v not in (None, [], False) and k != "text"}
        for key in ("since", "until"):
            if key in out:
                out[key] = out[key].isoformat(timespec="minutes")
        return out


def _take(text: str, pattern: str) -> tuple[bool, str]:
    """Find a phrase and blank it out, so a later rule can't read the same words again."""
    rest, found = re.subn(pattern, " ", text)
    return bool(found), rest


def _window(text: str, now: datetime) -> tuple[datetime | None, datetime | None, str | None, str]:
    """A time window ("today", "yesterday", "last 24 hours", "past week", "6h") as (since, until, label, rest)."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if m := re.search(r"\btoday'?s?\b|\btonight\b|\bthis morning\b", text):
        return midnight, None, "today", text[:m.start()] + " " + text[m.end():]
    if m := re.search(r"\byesterday'?s?\b", text):
        return midnight - timedelta(days=1), midnight, "yesterday", text[:m.start()] + " " + text[m.end():]
    units = {"min": 1, "minute": 1, "h": 60, "hr": 60, "hour": 60, "d": 1440, "day": 1440, "week": 10080,
             "month": 43200}
    m = (re.search(r"\b(?:last|past|previous|this)\s+(\d+\s*)?(minute|min|hour|hr|day|week|month)s?\b", text)
         or re.search(r"\b(\d+)\s*(h|hrs?|hours?|d|days?)\b", text))
    if not m:
        return None, None, None, text
    count, unit = int(m.group(1) or 1), m.group(2).rstrip("s")
    name = {1: "minute", 60: "hour", 1440: "day", 10080: "week", 43200: "month"}[units[unit]]
    label = f"last {count} {name}s" if count > 1 else f"last {name}"
    return now - timedelta(minutes=count * units[unit]), None, label, text[:m.start()] + " " + text[m.end():]


def _find_user(db: Session, text: str, original: str) -> User | None:
    """The customer a question names: full name, else surname, else first name. Short first names such as "Dev"
    count only when capitalized, so ordinary words never match a customer."""
    words = set(re.findall(r"[a-z]+", text.replace("'s", "")))
    best: tuple[int, User] | None = None
    for user in db.scalars(select(User).order_by(User.id)):
        first, *_, last = user.name.lower().split()
        if user.name.lower() in text:
            rank = 3
        elif last in words:
            rank = 2
        elif first in words and (len(first) > 3 or re.search(rf"\b{re.escape(first.title())}\b", original)):
            rank = 1
        else:
            continue
        if best is None or rank > best[0]:
            best = (rank, user)
    return best[1] if best else None


def parse_question(db: Session, question: str) -> Question:
    """Turn free text into explicit search terms. Matched phrases are blanked out as they are used, so "password
    reset after failures" names a signal and is not read again as a failed outcome."""
    text = _normalize(question)
    q = Question(text=text)
    if m := INCIDENT_REF.search(text):
        q.incident_id = int(m.group(1))
    if m := EVENT_REF.search(text):
        q.event_id = int(m.group(1))
    if m := USER_REF.search(text):
        q.user_id = f"USR-{m.group(1)}"
    plain = " ".join(re.sub(r"[-_/]+", " ", text).split())
    rest = plain
    for ref in (INCIDENT_REF, EVENT_REF, USER_REF):
        rest = ref.sub(" ", rest)
    for title, pattern in PATTERN_PHRASES.items():
        found, rest = _take(rest, pattern)
        q.patterns += [title] if found else []
    for name, pattern in SIGNAL_PHRASES.items():
        found, rest = _take(rest, pattern)
        q.signals += [name] if found else []
    for pattern, labels in PLACES:
        found, rest = _take(rest, pattern)
        q.places += labels if found else ()
    if re.search(r"\bUS\b", question):  # only in capitals: "us" is usually the pronoun
        q.places += USA
    q.since, q.until, q.window, rest = _window(rest, utcnow())
    levels: set[str] = set()
    for named, pattern in LEVEL_PHRASES:
        found, rest = _take(rest, pattern)
        levels |= set(named) if found else set()
    for named, pattern in STATUS_PHRASES:
        found, rest = _take(rest, pattern)
        q.statuses = sorted({*q.statuses, *named}) if found else q.statuses
    q.event_types = [kind for kind, pattern in EVENT_TYPE_PHRASES.items() if re.search(pattern, rest)]
    q.outcome = next((outcome for outcome, pattern in OUTCOME_PHRASES if re.search(pattern, rest)), None)
    # "suspicious transactions", "fraudulent payments": a vague risk word about transactions names that signal.
    if "transaction" in q.event_types and not q.signals and re.search(r"\b(?:suspicious|fraud\w*)\b", rest):
        q.signals.append("Suspicious transaction")
    if not levels and not q.signals and re.search(FLAGGED, rest):
        levels = {"MEDIUM", "HIGH", "CRITICAL"}
    q.levels = sorted(levels, key=LEVEL_ORDER.index)
    q.event_types = [kind for kind in q.event_types if kind not in {IMPLIED_TYPES.get(s) for s in q.signals}]
    q.places = list(dict.fromkeys(q.places))
    if q.user_id is None and (user := _find_user(db, text, question)):
        q.user_id = user.id
    q.subject = next((subject for subject, pattern in SUBJECTS if re.search(pattern, plain)), None)
    q.recent, q.one = bool(re.search(RECENT, plain)), bool(re.search(TOP_CUSTOMER, plain))
    q.intent = _intent(q, plain)
    return q


def _intent(q: Question, plain: str) -> str:
    named = bool(q.signals or q.patterns)
    narrowed = bool(q.places or q.levels or q.statuses or q.outcome or q.since)
    if q.incident_id is not None or q.event_id is not None or q.user_id:
        return "focus"
    if re.search(TOP_INCIDENT, plain):
        return "top"
    if not (named or narrowed or q.event_types or q.subject) and re.search(SCORING, plain):
        return "scoring"
    if (named and not narrowed and q.subject in (None, "events") and re.search(DEFINE, plain)
            and not re.search(LISTING, plain)):
        return "define"
    if re.search(COUNT, plain):
        return "count"
    if not (named or q.places or q.levels or q.statuses or q.event_types or q.outcome or q.subject) \
            and re.search(SUMMARY, plain):
        return "summary"
    return "list"


# --- retrieval: only the records that match ----------------------------------------------------------------
def _names(db: Session, user_ids: set[str]) -> dict[str, str]:
    return dict(db.execute(select(User.id, User.name).where(User.id.in_(user_ids))).all()) if user_ids else {}


def _brief(e: Event, names: dict[str, str]) -> dict:
    """The compact event shape used in lists (a focused event gets the full one, with contributions)."""
    return {"event_id": event_ref(e.id), "user_id": e.user_id, "user_name": names.get(e.user_id, "?"),
            "event_type": e.event_type, "timestamp": e.timestamp.isoformat(), "location": e.location,
            "status": e.status, "risk_score": e.risk_score, "risk_level": e.risk_level, "signals": e.signals,
            "incident_id": incident_ref(e.incident_id)}


def _event_conditions(q: Question) -> list:
    """SQL conditions an event must meet. Each named signal is an EXISTS on the indexed risk_signals table."""
    conds = [exists().where(RiskSignal.event_id == Event.id, RiskSignal.name == name) for name in q.signals]
    for column, values in ((Event.user_id, [q.user_id] if q.user_id else []), (Event.event_type, q.event_types),
                           (Event.location, q.places), (Event.risk_level, q.levels),
                           (Event.status, [q.outcome] if q.outcome else [])):
        if values:
            conds.append(column.in_(values))
    if q.since:
        conds.append(Event.timestamp >= q.since)
    if q.until:
        conds.append(Event.timestamp < q.until)
    return conds


def _incident_order(q: Question) -> tuple:
    if q.recent:
        return (Incident.updated.desc(),)
    return Incident.status == "RESOLVED", Incident.risk_score.desc(), Incident.updated.desc()


def _match_incidents(db: Session, q: Question) -> list[Incident]:
    """Every matching incident, best first. SQL filters status, severity, customer, time and (through the incident's
    events) place, type and outcome; signals and pattern titles are then checked on each incident itself."""
    conds = []
    for column, values in ((Incident.user_id, [q.user_id] if q.user_id else []), (Incident.status, q.statuses),
                           (Incident.severity, q.levels)):
        if values:
            conds.append(column.in_(values))
    if q.since:
        conds.append(Incident.updated >= q.since)
    if q.until:
        conds.append(Incident.created < q.until)
    per_event = ((Event.location, q.places), (Event.event_type, q.event_types),
                 (Event.status, [q.outcome] if q.outcome else []))
    on_events = [column.in_(values) for column, values in per_event if values]
    if on_events:
        conds.append(exists().where(Event.incident_id == Incident.id, *on_events))
    return [i for i in db.scalars(select(Incident).where(*conds).order_by(*_incident_order(q)))
            if set(q.signals) <= set(i.signals) and (not q.patterns or incident_title(i.signals) in q.patterns)]


def search_incidents(db: Session, q: Question) -> dict:
    matched = _match_incidents(db, q)
    shown = [i.id for i in matched[:LIST_LIMIT]]
    items = incidents_page(db, select(Incident).where(Incident.id.in_(shown)).order_by(*_incident_order(q))) \
        if shown else []
    return {"total": len(matched), "by_status": dict(Counter(i.status for i in matched)), "items": items}


def search_events(db: Session, q: Question) -> dict:
    conds = _event_conditions(q)
    if q.patterns:  # an event belongs to a pattern when its incident carries that title
        titled = [i.id for i in db.scalars(select(Incident)) if incident_title(i.signals) in q.patterns]
        conds.append(Event.incident_id.in_(titled))
    order = (Event.timestamp.desc(),) if q.recent else (Event.risk_score.desc(), Event.timestamp.desc())
    events = db.scalars(select(Event).where(*conds).order_by(*order).limit(LIST_LIMIT)).all()
    by_level = dict(db.execute(select(Event.risk_level, func.count()).where(*conds).group_by(Event.risk_level)).all())
    names = _names(db, {e.user_id for e in events})
    return {"total": sum(by_level.values()), "by_level": by_level, "items": [_brief(e, names) for e in events]}


def _customer(u: dict) -> dict:
    keys = ("user_id", "name", "risk_score", "risk_level", "open_incidents", "last_activity")
    return {key: u[key] for key in keys}


def search_customers(db: Session, q: Question) -> dict:
    """Customers behind the matching events or incidents. With no terms: everyone at elevated risk right now."""
    people = {u["user_id"]: u for u in users_overview(db)}
    matches: dict[str, int | None]
    if q.signals or q.places or q.event_types or q.outcome or q.since:
        matches = dict(db.execute(select(Event.user_id, func.count()).where(*_event_conditions(q))
                                  .group_by(Event.user_id)).all())
    elif q.statuses or q.patterns:
        matches = dict(Counter(i.user_id for i in _match_incidents(db, q)))
    else:
        wanted = set(q.levels or ("MEDIUM", "HIGH", "CRITICAL"))
        matches = {uid: None for uid, u in people.items() if u["risk_level"] in wanted}
    ranked = sorted((uid for uid in matches if uid in people),
                    key=lambda uid: (-people[uid]["risk_score"], -(matches[uid] or 0), uid))
    items = [{**_customer(people[uid]), **({"matches": matches[uid]} if matches[uid] is not None else {})}
             for uid in ranked[:LIST_LIMIT]]
    return {"total": len(ranked), "items": items}


SEARCHES = {"incidents": search_incidents, "events": search_events, "customers": search_customers}


def overview(db: Session, q: Question) -> dict:
    """The state of play for a summary question: activity in the window, plus the incident queue right now."""
    since = q.since or utcnow() - timedelta(hours=24)
    window = [Event.timestamp >= since] + ([Event.timestamp < q.until] if q.until else [])
    levels = dict(db.execute(select(Event.risk_level, func.count()).where(*window).group_by(Event.risk_level)).all())
    top_signals = db.execute(select(RiskSignal.name, func.count()).join(Event, RiskSignal.event_id == Event.id)
                             .where(*window, RiskSignal.weight > 0).group_by(RiskSignal.name)
                             .order_by(func.count().desc()).limit(4)).all()
    unresolved = Incident.status != "RESOLVED"
    created = [Incident.created >= since] + ([Incident.created < q.until] if q.until else [])
    queue = db.execute(select(Incident.status, func.count()).where(unresolved).group_by(Incident.status)).all()
    critical = select(func.count()).select_from(Incident).where(unresolved, Incident.severity == "CRITICAL")
    urgent = select(Incident).where(unresolved).order_by(Incident.risk_score.desc(), Incident.updated.desc())
    riskiest = sorted(users_overview(db), key=lambda u: (-u["risk_score"], u["user_id"]))[:3]
    return {
        "window": q.window or "last 24 hours", "events": sum(levels.values()),
        "high_risk": levels.get("HIGH", 0) + levels.get("CRITICAL", 0),
        "top_signals": [[name, count] for name, count in top_signals], "queue": dict(queue),
        "critical": db.scalar(critical),
        "new_incidents": db.scalar(select(func.count()).select_from(Incident).where(*created)),
        "urgent": incidents_page(db, urgent.limit(3)), "riskiest": [_customer(u) for u in riskiest],
    }


def definitions(db: Session, q: Question) -> list[dict]:
    """What each named signal or pattern means, its exact trigger, and where it has been seen."""
    incidents = db.scalars(select(Incident).order_by(Incident.updated.desc())).all()
    out = []
    for name in q.signals:
        signal = rules.SIGNALS[name]
        seen = [i for i in incidents if name in i.signals]
        out.append({"name": name, "weight": signal.weight, "description": signal.description,
                    "trigger": TRIGGERS.get(name), "mitre": signal.mitre, "incidents": len(seen),
                    "events": db.scalar(select(func.count()).select_from(RiskSignal).where(RiskSignal.name == name)),
                    "latest_incident": incident_ref(seen[0].id) if seen else None})
    for title in q.patterns:
        seen = [i for i in incidents if incident_title(i.signals) == title]
        out.append({"name": title, "requires": pattern_signals(title), "incidents": len(seen),
                    "latest_incident": incident_ref(seen[0].id) if seen else None})
    return out


def scoring_model() -> dict:
    levels, ceiling = [], 100
    for level, floor in rules.LEVELS:  # highest first
        levels.append({"level": level, "from": floor, "to": ceiling, "action": rules.ACTIONS[level]})
        ceiling = floor - 1
    return {"weights": dict(rules.WEIGHTS), "levels": levels, "incident_open": rules.INCIDENT_OPEN_SCORE,
            "incident_join": rules.INCIDENT_JOIN_SCORE, "incident_pull": rules.INCIDENT_PULL_SCORE,
            "window_minutes": rules.minutes(rules.CORRELATION_WINDOW)}


def _event_focus(db: Session, event: Event) -> dict:
    user = db.get(User, event.user_id)
    incident = db.get(Incident, event.incident_id) if event.incident_id else None
    return {**event_dict(event), "user_name": user.name if user else "?",
            "incident_title": incident_title(incident.signals) if incident else None}


def _user_focus(db: Session, user: User, q: Question) -> dict:
    recent = db.scalars(select(Event).where(Event.user_id == user.id).order_by(Event.timestamp.desc()).limit(10)).all()
    profile = {"user_id": user.id, "name": user.name, "home_location": user.home_location, "segment": user.segment,
               "risk": user_risk(db, user.id), "recent_events": [_brief(e, {user.id: user.name}) for e in recent]}
    if q.subject == "incidents":
        profile["matches"] = {"kind": "incidents", **search_incidents(db, q)}
    elif q.filtered:
        profile["matches"] = {"kind": "events", **search_events(db, q)}
    return profile


def _wider(db: Session, q: Question, subject: str) -> dict | None:
    """For an empty result: the same search without the time window, else without the place."""
    relaxations = (("time window", {"since": None, "until": None, "window": None}), ("place", {"places": []}))
    for dropped, relaxed in relaxations:
        if any(getattr(q, key) for key in relaxed):
            result = SEARCHES[subject](db, replace(q, **relaxed))
            if result["total"]:
                return {"dropped": dropped, **result}
    return None


def _top_incident(db: Session) -> Incident | None:
    return db.scalars(select(Incident).order_by(*_incident_order(Question(text="")))).first()


def gather_context(db: Session, question: str) -> dict:
    """Parse the question, then collect only the records it is about (this is the model's entire world)."""
    q = parse_question(db, question)
    ctx: dict = {}
    if q.incident_id is not None:
        if incident := db.get(Incident, q.incident_id):
            ctx["incident"] = incident_detail(db, incident)
        else:
            q.not_found.append(f"INC-{q.incident_id:04d}")
    if q.event_id is not None:
        if event := db.get(Event, q.event_id):
            ctx["event"] = _event_focus(db, event)
        else:
            q.not_found.append(f"EVT-{q.event_id:05d}")
    if q.user_id:
        if user := db.get(User, q.user_id):
            ctx["user"] = _user_focus(db, user, q)
        else:
            q.not_found.append(q.user_id)
            q.user_id = None
    if not any(key in ctx for key in ("incident", "event", "user")):
        if q.intent == "top" and (top := _top_incident(db)):
            ctx["incident"] = incident_detail(db, top)
        elif q.intent == "scoring":
            ctx["scoring"] = scoring_model()
        elif q.intent == "define":
            ctx["definitions"] = definitions(db, q)
        elif q.intent == "summary":
            ctx["overview"] = overview(db, q)
        elif q.intent != "focus" and (q.filtered or q.subject):
            subject = q.subject or ("incidents" if q.signals or q.patterns or q.statuses or q.levels else "events")
            ctx["subject"], ctx[subject] = subject, SEARCHES[subject](db, q)
            if not ctx[subject]["total"]:  # nothing matched: say so, then show what a looser search finds
                ctx["wider"] = _wider(db, q, subject)
            if q.signals or q.patterns:
                ctx["definitions"] = definitions(db, q)
        else:  # nothing specific asked: the incident queue, most urgent first
            ctx["subject"], ctx["incidents"] = "incidents", search_incidents(db, Question(text=q.text))
    ctx["question"] = q.summary()
    if q.not_found:
        ctx["not_found"] = q.not_found
    return ctx


def engine_decision(ctx: dict) -> dict | None:
    """The deterministic verdict the explanation is about (shown separately in the UI)."""
    keys = ("risk_score", "risk_level", "signals", "recommended_action")
    for kind, ref in (("incident", "incident_id"), ("event", "event_id")):
        if record := ctx.get(kind):
            return {"subject": record[ref], **{key: record[key] for key in keys}}
    if user := ctx.get("user"):
        return {"subject": user["user_id"], **{key: user["risk"][key] for key in keys}}
    return None


def _ref(item: dict) -> str:
    if "event_id" in item:
        return item["event_id"]
    return item["incident_id"] if "title" in item else item["user_id"]


def sources(ctx: dict) -> list[str]:
    """Every record the answer used, focused records first (the UI turns them into links)."""
    refs = [ctx[kind][ref] for kind, ref in (("incident", "incident_id"), ("event", "event_id"), ("user", "user_id"))
            if kind in ctx]
    if (event := ctx.get("event")) and event["incident_id"]:
        refs.append(event["incident_id"])
    for result in (ctx.get("user", {}).get("matches"), ctx.get(ctx.get("subject", "")), ctx.get("wider")):
        refs += [_ref(item) for item in result["items"]] if result else []
    refs += [_ref(item) for item in ctx.get("overview", {}).get("urgent", [])]
    if ctx["question"].get("intent") == "define":  # a definition names its latest incident
        refs += [d["latest_incident"] for d in ctx["definitions"] if d["latest_incident"]]
    return list(dict.fromkeys(refs))[:LIST_LIMIT + 2]


# --- the deterministic analyst: markdown from the same context the model would get -------------------------
def _when(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b %H:%M")


def _plural(word: str, n: int) -> str:
    return word if n == 1 else f"{word}s"


def _signal_details(incident: dict) -> dict[str, str]:
    """First concrete detail recorded for each signal across the incident's events."""
    details: dict[str, str] = {}
    for event in incident["timeline"]:
        for c in event.get("contributions") or []:
            details.setdefault(c["signal"], c["detail"])
    return details


def _incident_line(i: dict) -> str:
    return (f"- **{i['incident_id']}** {i['title']} — {i['severity']} {i['risk_score']} · {i['user_name']} · "
            f"{i['status'].lower()} · {_when(i['updated'])}")


def _event_line(e: dict) -> str:
    risky = ", ".join(s for s in e["signals"] if rules.WEIGHTS[s] > 0)
    return (f"- **{e['event_id']}** {e['event_type'].replace('_', ' ')} ({e['status']}) in {e['location']} · "
            f"{_when(e['timestamp'])} · {e['risk_level']} {e['risk_score']} · {e['user_name']}"
            + (f" · {risky}" if risky else ""))


def _customer_line(u: dict) -> str:
    matches = f" · {u['matches']} matching" if "matches" in u else ""
    return (f"- **{u['name']}** ({u['user_id']}) — {u['risk_score']} {u['risk_level']} · {u['open_incidents']} open "
            f"{_plural('incident', u['open_incidents'])}{matches}")


LINES = {"incidents": _incident_line, "events": _event_line, "customers": _customer_line}
NOUNS = {"incidents": "incident", "events": "event", "customers": "customer"}


def _lines(kind: str, items: list[dict]) -> str:
    return "\n".join(LINES[kind](item) for item in items)


def _terms(q: dict) -> str:
    """The search terms read back to the user, e.g. "Impossible travel · Lagos · last 24 hours"."""
    parts = [*q.get("patterns", []), *q.get("signals", [])]
    levels = tuple(q.get("levels", ()))
    if levels:
        parts.append({("HIGH", "CRITICAL"): "HIGH or above", ("MEDIUM", "HIGH", "CRITICAL"): "MEDIUM or above"}
                     .get(levels, " or ".join(levels)))
    statuses = tuple(q.get("statuses", ()))
    if statuses:
        unresolved = statuses == ("INVESTIGATING", "OPEN")
        parts.append("unresolved" if unresolved else " or ".join(s.lower() for s in statuses))
    parts += [kind.replace("_", " ") for kind in q.get("event_types", [])]
    if outcome := q.get("outcome"):
        parts.append("failed" if outcome == "failure" else "successful")
    if places := q.get("places"):
        parts.append(" or ".join(dict.fromkeys(p.split(",")[0] for p in places)))
    if window := q.get("window"):
        parts.append(window)
    return " · ".join(parts)


def _breakdown(result: dict) -> str:
    if "by_status" in result:
        statuses = result["by_status"]
        counts = [f"{statuses[s]} {s.lower()}" for s in ("OPEN", "INVESTIGATING", "RESOLVED") if statuses.get(s)]
    else:
        levels = result["by_level"]
        counts = [f"{levels[lv]} {lv.lower()}" for lv in reversed(LEVEL_ORDER) if levels.get(lv)]
    return f" ({', '.join(counts)})" if counts else ""


def _explain_results(ctx: dict, q: dict) -> str:
    kind = ctx["subject"]
    result, terms, noun = ctx[kind], _terms(q), NOUNS[kind]
    total, shown = result["total"], len(result["items"])
    if not total:
        text = f"No {noun}s match *{terms}*." if terms else f"No {noun}s are recorded yet."
        if wide := ctx.get("wider"):
            n, where = wide["total"], "Without the time window" if wide["dropped"] == "time window" else "Elsewhere"
            text += f" {where} there {'is' if n == 1 else 'are'} **{n}**:\n{_lines(kind, wide['items'])}"
        elif terms:
            text += " Try fewer terms."
        return text
    if kind == "customers" and q.get("one"):
        top, *rest = result["items"]
        scope = f" matching *{terms}*" if terms else " right now"
        text = (f"The riskiest customer{scope} is **{top['name']}** ({top['user_id']}): {top['risk_score']}/100 "
                f"{top['risk_level']}, {top['open_incidents']} open {_plural('incident', top['open_incidents'])}.")
        return text + (f"\n\nNext:\n{_lines(kind, rest[:4])}" if rest else "")
    if not terms:
        heading = {"incidents": "Highest-risk incidents, unresolved first", "events": "Highest-risk events",
                   "customers": "Customers at elevated risk right now"}[kind]
        if q.get("recent"):
            heading = {"incidents": "Most recently updated incidents", "events": "Latest events"}.get(kind, heading)
        text = f"{heading} ({total} in total):"
    elif q.get("intent") == "count":
        breakdown = _breakdown(result) if kind != "customers" else ""
        text = f"**{total}** {_plural(noun, total)} {'matches' if total == 1 else 'match'} *{terms}*{breakdown}."
    else:
        more = f", showing the {shown} {'most recent' if q.get('recent') else 'riskiest'}" if total > shown else ""
        text = f"Found **{total}** {_plural(noun, total)} matching *{terms}*{more}:"
    text += f"\n{_lines(kind, result['items'])}"
    signals = [d for d in ctx.get("definitions", []) if "weight" in d]
    notes = [f"*{d['name']}* ({d['weight']:+d}): {d['description']}" for d in signals]
    return text + ("\n\n" + "\n".join(notes) if notes else "")


def _explain_incident(incident: dict, question: str) -> str:
    q = question.lower()
    details = _signal_details(incident)
    ranked = sorted(incident["signals"], key=lambda s: -rules.WEIGHTS[s])
    why = "\n".join(f"- **{s}** {rules.WEIGHTS[s]:+d} — {details.get(s, rules.SIGNALS[s].description)}"
                    for s in ranked)
    if "contribut" in q or "signal" in q:
        # The incident's score is its riskiest event's score, so break *that* event down.
        peak = max(incident["timeline"], key=lambda e: e["risk_score"])
        parts = "\n".join(f"- **{c['signal']}** {c['weight']:+d} — {c['detail']}" for c in peak["contributions"])
        total = sum(c["weight"] for c in peak["contributions"])
        clamp = f", clamped to {peak['risk_score']}" if total != peak["risk_score"] else ""
        return (f"**{incident['incident_id']}** scores **{incident['risk_score']}/100**, the score of its riskiest "
                f"event {peak['event_id']}, whose weights add up to {total}{clamp}:\n{parts}\n\n"
                f"All signals seen across its {incident['event_count']} events, heaviest first:\n{why}")
    steps = [f"- {_when(e['timestamp'])} · {e['event_type']} ({e['status']}) · {e['location']} · "
             f"score {e['risk_score']}" for e in incident["timeline"][:6]]
    if len(incident["timeline"]) > 6:
        steps.append(f"- …and {len(incident['timeline']) - 6} more")
    steps_text = "\n".join(steps)
    return (f"**{incident['incident_id']} · {incident['title']}** — {incident['severity']} "
            f"({incident['risk_score']}/100), status {incident['status']}, affecting {incident['user_name']} "
            f"({incident['user_id']}).\n\n{incident['event_count']} correlated events:\n{steps_text}\n\n"
            f"**Why it scored this high:**\n{why}\n\n**Recommended action:** {incident['recommended_action']}.")


def _explain_event(e: dict) -> str:
    parts = "\n".join(f"- **{c['signal']}** {c['weight']:+d} — {c['detail']}" for c in e["contributions"]) \
        or "- No signals fired."
    total = sum(c["weight"] for c in e["contributions"])
    clamp = f", clamped to {e['risk_score']}" if total != e["risk_score"] else ""
    amount = f" of ${e['transaction_amount']:,.2f}" if e["transaction_amount"] else ""
    resource = f" to {e['resource_accessed']}" if e["resource_accessed"] else ""
    incident = f"Part of **{e['incident_id']}** ({e['incident_title']})." if e["incident_id"] \
        else "Not part of any incident."
    return (f"**{e['event_id']}** · {e['event_type'].replace('_', ' ')}{amount}{resource} ({e['status']}) by "
            f"{e['user_name']} ({e['user_id']}) in {e['location']}, {_when(e['timestamp'])} UTC.\n\n"
            f"It scored **{e['risk_score']}/100 ({e['risk_level']})**; its weights add up to {total}{clamp}:\n"
            f"{parts}\n\n{incident}\n\n**Recommended action:** {e['recommended_action']}.")


def _explain_user(user: dict, q: dict) -> str:
    risk = user["risk"]
    text = (f"**{user['name']}** ({user['user_id']}, {user['segment']}, home {user['home_location']}) currently "
            f"scores **{risk['risk_score']}/100 ({risk['risk_level']})** over their last 10 events.\n\n")
    if matches := user.get("matches"):
        kind, n, terms = matches["kind"], matches["total"], _terms(q)
        label = f" matching *{terms}*" if terms else ""
        text += f"**{n}** {_plural(NOUNS[kind], n)}{label}:\n{_lines(kind, matches['items'])}" if n \
            else f"No {NOUNS[kind]}s{label}."
    elif q.get("recent"):
        text += f"Latest activity:\n{_lines('events', user['recent_events'][:5])}"
    else:
        notable = sorted(user["recent_events"], key=lambda e: -e["risk_score"])[:3]
        text += f"Most notable activity:\n{_lines('events', notable)}"
    return f"{text}\n\n**Recommended action:** {risk['recommended_action']}."


def _explain_definitions(defs: list[dict]) -> str:
    blocks = []
    for d in defs:
        incidents = f"**{d['incidents']}** {_plural('incident', d['incidents'])}"
        latest = f"; the latest is {d['latest_incident']}" if d["latest_incident"] else ""
        if "weight" in d:
            mitre = f" MITRE ATT&CK: {d['mitre']['id']} ({d['mitre']['name']})." if d["mitre"] else ""
            events = f"**{d['events']}** {_plural('event', d['events'])}"
            blocks.append(f"**{d['name']}** ({d['weight']:+d} to the score): {d['description']} {d['trigger'] or ''}"
                          f"{mitre}\n\nSeen on {events} in {incidents}{latest}.")
        else:
            combos = " or ".join(" + ".join(combo) for combo in d["requires"])
            blocks.append(f"**{d['name']}** is the title the engine gives an incident whose events combine {combos}."
                          f"\n\nSeen in {incidents}{latest}.")
    return "\n\n".join(blocks)


def _explain_scoring(m: dict) -> str:
    weights = ", ".join(f"{name} {weight:+d}" for name, weight in m["weights"].items())
    levels = "\n".join(f"- **{lv['level']}** {lv['from']}–{lv['to']}: {lv['action']}" for lv in m["levels"])
    return (f"Each event is scored by an additive rulebook: every signal that fires adds its weight, and the total "
            f"is clamped to 0–100.\n\n**Weights:** {weights}.\n\n**Levels and actions:**\n{levels}\n\n"
            f"Events scoring {m['incident_open']}+ open an incident; events scoring {m['incident_join']}+ join the "
            f"customer's open incident within {m['window_minutes']} minutes, and earlier events scoring "
            f"{m['incident_pull']}+ (or failing) are pulled in. An incident's score is its riskiest event's score.")


def _explain_overview(o: dict) -> str:
    signals = ", ".join(f"{name} ({count})" for name, count in o["top_signals"]) or "none"
    open_, investigating = o["queue"].get("OPEN", 0), o["queue"].get("INVESTIGATING", 0)
    people = ", ".join(f"{u['name']} ({u['risk_score']})" for u in o["riskiest"])
    urgent = _lines("incidents", o["urgent"]) or "- none"
    return (f"**Overview · {o['window']}**\n- **{o['events']}** events, **{o['high_risk']}** of them HIGH or "
            f"CRITICAL\n- Most frequent signals: {signals}\n- **{o['new_incidents']}** new "
            f"{_plural('incident', o['new_incidents'])}; the queue holds **{open_ + investigating}** unresolved "
            f"({open_} open, {investigating} investigating), **{o['critical']}** critical\n"
            f"- Riskiest customers right now: {people}\n\n**Most urgent:**\n{urgent}")


def deterministic_answer(ctx: dict, question: str) -> str:
    q = ctx.get("question", {})
    focused = any(key in ctx for key in ("incident", "event", "user"))
    prefix = ""
    if ctx.get("not_found"):
        tail = "." if focused else ", so here is the overall picture."
        prefix = f"I couldn't find {', '.join(ctx['not_found'])}{tail}\n\n"
    if incident := ctx.get("incident"):
        return prefix + _explain_incident(incident, question)
    if event := ctx.get("event"):
        return prefix + _explain_event(event)
    if user := ctx.get("user"):
        return prefix + _explain_user(user, q)
    if "scoring" in ctx:
        return _explain_scoring(ctx["scoring"])
    if "overview" in ctx:
        return _explain_overview(ctx["overview"])
    if q.get("intent") == "define":
        return _explain_definitions(ctx["definitions"])
    return prefix + _explain_results(ctx, q)


def _ask_openai(ctx: dict, question: str) -> str:
    response = httpx.post(
        f"{settings.openai_base_url}/chat/completions",
        timeout=20,
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={"model": settings.openai_model, "temperature": 0.2, "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{json.dumps(ctx, default=str)[:14000]}\n\nQuestion: {question}"},
        ]},
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def ask(db: Session, question: str) -> dict:
    ctx = gather_context(db, question)
    answer = {"decision": engine_decision(ctx), "sources": sources(ctx), "note": None}
    if settings.openai_api_key:
        try:
            return {**answer, "explanation": _ask_openai(ctx, question), "source": "openai",
                    "model": settings.openai_model}
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            log.warning("OpenAI request failed: %s", exc)
            answer["note"] = "OpenAI was unavailable, so the deterministic analyst answered."
    return {**answer, "explanation": deterministic_answer(ctx, question), "source": "deterministic", "model": None}
