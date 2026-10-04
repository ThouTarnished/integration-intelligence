import dataclasses

import httpx
from sqlalchemy import func, select

from iip import analyst, rules
from iip.database import Incident


def ask(client, question: str) -> dict:
    return client.post("/api/v1/ai/ask", json={"question": question}).json()


def test_explains_top_incident_deterministically(client):
    answer = ask(client, "Why was this incident considered high risk?")
    assert answer["source"] == "deterministic" and answer["decision"]
    assert answer["decision"]["subject"] in answer["explanation"] and answer["sources"]


def test_focuses_on_a_named_incident_and_user(client):
    incident_id = client.get("/api/v1/incidents").json()[0]["incident_id"]
    assert ask(client, f"Summarize {incident_id}")["decision"]["subject"] == incident_id
    assert ask(client, "What is USR-1004 doing?")["decision"]["subject"] == "USR-1004"
    assert ask(client, "Anything odd about Fenwick?")["decision"]["subject"] == "USR-1001"


def test_reports_missing_records(client):
    answer = ask(client, "Explain INC-9999")
    assert "INC-9999" in answer["explanation"] and answer["decision"] is None


def test_rejects_bad_questions(client):
    assert client.post("/api/v1/ai/ask", json={"question": "?"}).status_code == 422


def test_falls_back_when_openai_fails(db, monkeypatch):
    monkeypatch.setattr(analyst, "settings", dataclasses.replace(analyst.settings, openai_api_key="sk-test"))

    def boom(*_, **__):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(analyst.httpx, "post", boom)
    answer = analyst.ask(db, "Show me users with unusual activity")
    assert answer["source"] == "deterministic" and "unavailable" in answer["note"]


def test_signal_breakdown_adds_up_to_the_score(client):
    """An incident scores its riskiest event's score, so the breakdown must add up to exactly that."""
    for summary in client.get("/api/v1/incidents?limit=15").json():
        detail = client.get(f"/api/v1/incidents/{summary['incident_id']}").json()
        peak = max(detail["timeline"], key=lambda e: e["risk_score"])
        total = sum(c["weight"] for c in peak["contributions"])
        text = ask(client, f"Which signals contributed to {summary['incident_id']}?")["explanation"]
        assert peak["event_id"] in text and f"add up to {total}" in text
        assert min(max(total, 0), 100) == detail["risk_score"]


def test_parses_search_terms(db):
    q = analyst.parse_question(db, "Show failed sign-ins from Russia in the last 24h for Kira")
    assert (q.user_id, q.event_types, q.outcome, q.places) == ("USR-1011", ["login"], "failure", ["Moscow, Russia"])
    assert q.window == "last 24 hours" and q.since is not None
    q = analyst.parse_question(db, "How many critical incidents are open?")
    assert (q.intent, q.subject) == ("count", "incidents")
    assert (q.levels, q.statuses) == (["CRITICAL"], ["INVESTIGATING", "OPEN"])
    assert analyst.parse_question(db, "tell me about incident 12").incident_id == 12
    assert analyst.parse_question(db, "show dev environment events").user_id is None  # a word, not Dev Okonkwo


def test_signal_search_lists_only_matching_incidents(client):
    answer = ask(client, "Show me impossible travel incidents")
    refs = [ref for ref in answer["sources"] if ref.startswith("INC-")]
    assert refs and answer["decision"] is None
    assert all("Impossible travel" in client.get(f"/api/v1/incidents/{ref}").json()["signals"] for ref in refs)


def test_counts_agree_with_the_database(client, db):
    expected = db.scalar(select(func.count()).select_from(Incident)
                         .where(Incident.severity == "CRITICAL", Incident.status != "RESOLVED"))
    text = ask(client, "How many critical incidents are open?")["explanation"]
    assert text.startswith(f"**{expected}** ") if expected else text.startswith("No incidents")


def test_explains_an_event(client):
    event = client.get("/api/v1/events", params={"limit": 1}).json()["items"][0]
    answer = ask(client, f"Why was {event['event_id']} scored like this?")
    assert answer["decision"]["subject"] == event["event_id"]
    assert f"{event['risk_score']}/100" in answer["explanation"]


def test_defines_signals_with_their_real_thresholds(client):
    answer = ask(client, "What is impossible travel?")
    assert f"{rules.IMPOSSIBLE_SPEED_KMH} km/h" in answer["explanation"] and answer["decision"] is None
    assert f"{rules.WEIGHTS['Impossible travel']:+d}" in answer["explanation"]


def test_says_so_when_nothing_matches(client):
    text = ask(client, "Show password spray incidents in Tokyo")["explanation"]
    assert text.startswith("No incidents match *Password spray · Tokyo*")


def test_off_topic_questions_say_so(client, db, monkeypatch):
    """A question about something else is told so and small talk gets a reply, with no records and no model call;
    vague questions about the platform still get the incident queue."""
    assert "INC-" in ask(client, "What should I worry about?")["explanation"]
    assert ask(client, "hi")["explanation"].startswith("Hi!")  # two letters are enough for a greeting
    assert ask(client, "thanks!")["explanation"].startswith("Happy to help!")
    for question in ("What's the weather in Dubai?", "Who won the world cup?", "How high is Mount Everest?"):
        assert analyst.parse_question(db, question).intent == "unrelated", question
    monkeypatch.setattr(analyst, "settings", dataclasses.replace(analyst.settings, openai_api_key="sk-test"))

    def no_model(*_, **__):
        raise AssertionError("an off-topic question must not reach the model")

    monkeypatch.setattr(analyst.httpx, "post", no_model)
    answer = analyst.ask(db, "Shawerma")
    assert answer["explanation"].startswith("**Not related to the platform.** I couldn't find anything about “Shawerma")
    assert (answer["decision"], answer["sources"], answer["source"]) == (None, [], "deterministic")
