"""Synthetic (fictional) data and attack-scenario generators.

Every person is invented and every IP comes from the RFC 5737 documentation ranges
(203.0.113.0/24 behaves "clean", 198.51.100.0/24 is "flagged"), so nothing here is real.
The same generators power the seeder, the Simulation Center and live traffic.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import utcnow
from .database import Device, Incident, User
from .pipeline import process_event

FIRST = ["Ayla", "Bram", "Cora", "Dev", "Elio", "Fara", "Gus", "Hana", "Ivo", "Juno", "Kira", "Lev", "Mira",
         "Nico", "Odalys", "Pax", "Quin", "Rhea", "Sol", "Tavi", "Uma", "Vik", "Wren", "Xan", "Yara"]
LAST = ["Fenwick", "Calloway", "Draven", "Okonkwo", "Lindqvist", "Marchetti", "Tanaka", "Voss", "Halloran",
        "Brightwater", "Castellan", "Dunmore", "Eastwood", "Farrow", "Grimaldi", "Hartwell", "Ingram", "Jessop",
        "Kovacs", "Larkin", "Moreau", "Northcott", "Ostrander", "Pembroke", "Quillfeather"]
HOMES = ["Abu Dhabi, UAE", "Dubai, UAE", "London, UK", "Berlin, Germany"]
FOREIGN = ["Singapore", "New York, USA", "Lagos, Nigeria", "Moscow, Russia", "Sao Paulo, Brazil"]
TRIP_DESTINATIONS = ["Paris, France", "Frankfurt, Germany", "Istanbul, Turkey", "Doha, Qatar", *HOMES]
SEGMENTS = ["Retail", "Premier", "Business"]
ROUTINE_RESOURCES = ["accounts-portal", "statements", "payments-api"]
USER_COUNT = 25


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    summary: str
    category: str  # baseline | benign | suspicious | attack | fraud


SCENARIOS: dict[str, Scenario] = {s.key: s for s in (
    Scenario("normal_login", "Normal login", "A routine sign-in from home on a trusted device.", "baseline"),
    Scenario("business_trip", "Business trip",
             "Sign-ins in two cities eight hours apart: plausible travel, so no impossible-travel flag.", "benign"),
    Scenario("new_device", "New device", "A sign-in from an unknown device in a foreign city.", "suspicious"),
    Scenario("brute_force", "Brute force",
             "Five rapid failed logins from a flagged IP on an unknown device.", "attack"),
    Scenario("impossible_travel", "Impossible travel", "Sign-ins from two continents twenty minutes apart.", "attack"),
    Scenario("suspicious_transaction", "Suspicious transaction",
             "A $12,500 transfer from a new device on a flagged IP.", "fraud"),
    Scenario("card_testing", "Card testing",
             "Three tiny probe payments in four minutes, then a $2,450 cash-out.", "fraud"),
    Scenario("password_reset_abuse", "Recovery abuse",
             "Failed logins, then a password reset and sign-in from the attacker's device.", "attack"),
    Scenario("password_spray", "Password spray",
             "One flagged IP tries a common password against six different accounts in four minutes.", "attack"),
    Scenario("account_takeover", "Account takeover",
             "Credential attack, foreign sign-in, admin console, then a $15,000 transfer.", "attack"),
)}
MULTI_ACCOUNT = {"password_spray"}
ATTACKS = [k for k, s in SCENARIOS.items() if s.category in ("attack", "fraud", "suspicious")]


def scenario_catalog() -> list[dict]:
    return [asdict(s) for s in SCENARIOS.values()]


def trusted_device(user_index: int, which: int = 0) -> str:
    return f"DEV-{2000 + user_index * 2 + which}"


def routine_event(user: User, device_id: str, ts: datetime, rnd: random.Random,
                  allow_transaction: bool = True) -> dict:
    """Ordinary activity: home city, trusted device, clean IP, the odd mistyped password."""
    kinds, weights = (["login", "transaction", "resource_access"], [5, 3, 2])
    kind = rnd.choices(kinds, weights)[0] if allow_transaction else rnd.choice(["login", "resource_access"])
    failed = kind == "login" and rnd.random() < 0.1
    return {
        "user_id": user.id, "event_type": kind, "timestamp": ts, "location": user.home_location,
        "ip_address": f"203.0.113.{rnd.randint(2, 250)}", "device_id": device_id,
        "failed_attempts": rnd.randint(1, 2) if failed else 0, "ip_reputation": "clean",
        "status": "failure" if failed else "success",
        "transaction_amount": round(rnd.uniform(20, 3500), 2) if kind == "transaction" else None,
        "resource_accessed": rnd.choice(ROUTINE_RESOURCES) if kind == "resource_access" else None,
    }


def scenario_events(name: str, user_id: str, home: str, device_id: str, start: datetime,
                    rnd: random.Random) -> list[dict]:
    """Raw event payloads for one scenario, starting at `start`."""
    foreign = rnd.choice([c for c in FOREIGN if c != home])
    clean_ip = f"203.0.113.{rnd.randint(2, 250)}"
    flagged_ip = f"198.51.100.{rnd.randint(2, 250)}"
    new_device = f"DEV-{rnd.randint(9000, 9999)}"
    attacker = {"ip_address": flagged_ip, "location": foreign, "device_id": new_device, "ip_reputation": "suspicious"}

    def ev(minute: float, event_type: str = "login", **overrides) -> dict:
        return {"user_id": user_id, "event_type": event_type, "timestamp": start + timedelta(minutes=minute),
                "ip_address": clean_ip, "location": home, "device_id": device_id, "failed_attempts": 0,
                "ip_reputation": "clean", "status": "success", **overrides}

    def failed_logins(n: int) -> list[dict]:
        return [ev(i, status="failure", failed_attempts=i + 1, device_new=(i == 0), **attacker) for i in range(n)]

    if name == "normal_login":
        return [ev(0)]
    if name == "business_trip":
        city = rnd.choice([c for c in TRIP_DESTINATIONS if c != home])
        return [ev(0), ev(8 * 60, location=city),
                ev(8 * 60 + 25, "transaction", location=city, transaction_amount=round(rnd.uniform(40, 400), 2))]
    if name == "new_device":
        return [ev(0, device_id=new_device, device_new=True, location=foreign)]
    if name == "brute_force":
        return failed_logins(5)
    if name == "impossible_travel":
        return [ev(0), ev(20, location=foreign, device_id=new_device, device_new=True)]
    if name == "suspicious_transaction":
        return [ev(0, "transaction", transaction_amount=12500.0, device_id=new_device, device_new=True,
                   ip_address=flagged_ip, ip_reputation="suspicious")]
    if name == "card_testing":
        probes = [ev(i * 1.5, "transaction", transaction_amount=round(rnd.uniform(1, 9), 2), device_new=(i == 0),
                     **attacker) for i in range(3)]
        return [*probes, ev(4, "transaction", transaction_amount=2450.0, **attacker)]
    if name == "password_reset_abuse":
        return [*failed_logins(3), ev(4, "password_reset", **attacker), ev(6, **attacker)]
    if name == "account_takeover":
        return [*failed_logins(3),
                ev(3, failed_attempts=3, device_new=True, **attacker),
                ev(4, "resource_access", resource_accessed="admin-console", **attacker),
                ev(5, "transaction", transaction_amount=15000.0, **attacker)]
    raise ValueError(f"Unknown scenario {name!r}")


def spray_events(targets: list[User], start: datetime, rnd: random.Random) -> list[dict]:
    """One attacker, one IP, one failed guess per account: the signature of a password spray."""
    ip, origin, device = f"198.51.100.{rnd.randint(2, 250)}", rnd.choice(FOREIGN), f"DEV-{rnd.randint(9000, 9999)}"
    return [{"user_id": u.id, "event_type": "login", "timestamp": start + timedelta(seconds=45 * i),
             "ip_address": ip, "location": origin, "device_id": device, "device_new": True,
             "failed_attempts": 1, "ip_reputation": "suspicious", "status": "failure"}
            for i, u in enumerate(targets)]


def plan_scenario(name: str, user: User, device_id: str, pool: list[User], end: datetime,
                  rnd: random.Random) -> list[dict]:
    """A scenario for `user` (plus extra victims from `pool` when it spans accounts), ending at `end`."""
    if name in MULTI_ACCOUNT:
        others = rnd.sample([u for u in pool if u.id != user.id], k=min(5, len(pool) - 1))
        events = spray_events([user, *others], end, rnd)
    else:
        events = scenario_events(name, user.id, user.home_location, device_id, end, rnd)
    return ending_at(events, end)


def ending_at(events: list[dict], end: datetime) -> list[dict]:
    """Shift a scenario in time so that its last event happens at `end`."""
    offset = end - max(e["timestamp"] for e in events)
    return [{**e, "timestamp": e["timestamp"] + offset} for e in events]


def seed(db: Session, seed_value: int = 42) -> None:
    """Populate an empty database with a reproducible week of NovaBank activity."""
    rnd = random.Random(seed_value)
    now = utcnow()
    users = [User(id=f"USR-{1001 + i}", name=f"{FIRST[i]} {LAST[i]}",
                  home_location=rnd.choice(HOMES), segment=rnd.choice(SEGMENTS)) for i in range(USER_COUNT)]
    db.add_all(users)
    db.flush()  # users must exist before the devices that reference them
    db.add_all(Device(id=trusted_device(i, k), user_id=u.id, trusted=True)
               for i, u in enumerate(users) for k in range(2))
    db.flush()

    # 1. A week of ordinary activity at home on trusted devices.
    plan: list[dict] = []
    for i, user in enumerate(users):
        for _ in range(rnd.randint(10, 18)):
            ts = now - timedelta(hours=rnd.uniform(2, 168))
            plan.append(routine_event(user, trusted_device(i, rnd.randint(0, 1)), ts, rnd))

    # 2. Legitimate business trips: real travel the engine must NOT call impossible.
    for i in rnd.sample(range(USER_COUNT), 4):
        user, depart = users[i], now - timedelta(hours=rnd.uniform(30, 140))
        away = (depart - timedelta(hours=1), depart + timedelta(hours=22))
        plan = [p for p in plan if not (p["user_id"] == user.id and away[0] <= p["timestamp"] <= away[1])]
        plan += scenario_events("business_trip", user.id, user.home_location, trusted_device(i), depart, rnd)

    # 3. Historical attacks scattered across the week.
    history = (["brute_force"] * 4 + ["impossible_travel"] * 3 + ["account_takeover"] * 3 +
               ["suspicious_transaction"] * 3 + ["new_device"] * 3 + ["card_testing"] * 2 +
               ["password_reset_abuse"] * 2)
    for name in history:
        i = rnd.randrange(USER_COUNT)
        start = now - timedelta(hours=rnd.uniform(1, 150))
        plan += scenario_events(name, users[i].id, users[i].home_location, trusted_device(i), start, rnd)
    plan += spray_events(rnd.sample(users, 6), now - timedelta(hours=rnd.uniform(30, 60)), rnd)

    # 4. Fresh attacks so the dashboard opens on active investigations.
    for name, minutes_ago, i in (("account_takeover", 45, 3), ("brute_force", 120, 11), ("card_testing", 15, 7)):
        start = now - timedelta(minutes=minutes_ago)
        plan += scenario_events(name, users[i].id, users[i].home_location, trusted_device(i), start, rnd)

    for payload in sorted(plan, key=lambda p: p["timestamp"]):
        process_event(db, payload, commit=False)
    db.flush()

    # Incidents older than a day have already been worked by analysts.
    for incident in db.scalars(select(Incident)):
        if incident.updated < now - timedelta(hours=24):
            incident.status = rnd.choice(["RESOLVED", "RESOLVED", "INVESTIGATING"])
    db.commit()
