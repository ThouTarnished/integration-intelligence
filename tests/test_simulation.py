"""Scenarios run through the real pipeline, so these double as end-to-end detection tests."""
import pytest
from conftest import AUTH

from iip.seed import SCENARIOS


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_every_scenario_runs(client, scenario):
    response = client.post(f"/api/v1/simulation/{scenario}", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert [s["stage"] for s in body["steps"]] == ["ingest", "normalize", "enrich", "score", "correlate", "publish"]
    assert body["events"] and body["top_event"]["risk_score"] == max(e["risk_score"] for e in body["events"])


@pytest.fixture
def fresh(client):
    """Detection assertions need a known history: earlier random scenarios may have touched any user."""
    client.post("/api/v1/simulation/reset", headers=AUTH)


def test_normal_login_opens_no_incident(client, fresh):
    body = client.post("/api/v1/simulation/normal_login", headers=AUTH).json()
    assert body["incident"] is None and body["top_event"]["risk_level"] == "LOW"


def test_business_trip_is_plausible(client, fresh):
    body = client.post("/api/v1/simulation/business_trip", headers=AUTH).json()
    signals = {s for e in body["events"] for s in e["signals"]}
    assert "Impossible travel" not in signals and body["incident"] is None


def test_brute_force_correlates_into_one_incident(client, fresh):
    body = client.post("/api/v1/simulation/brute_force?user_id=USR-1020", headers=AUTH).json()
    assert body["user"]["user_id"] == "USR-1020"
    assert body["incident"] and body["incident"]["event_count"] >= 5


def test_impossible_travel_is_flagged(client, fresh):
    body = client.post("/api/v1/simulation/impossible_travel?user_id=USR-1020", headers=AUTH).json()
    assert "Impossible travel" in body["top_event"]["signals"]
    assert body["top_event"]["context"]["travel"]["speed_kmh"] > 900


def test_targeting_an_unknown_user_is_404(client):
    assert client.post("/api/v1/simulation/brute_force?user_id=USR-0000", headers=AUTH).status_code == 404


def test_password_spray_spans_accounts(client):
    body = client.post("/api/v1/simulation/password_spray", headers=AUTH).json()
    assert len(body["affected_users"]) >= 5
    assert any("Password spray" in e["signals"] for e in body["events"])


def test_simulation_guards(client):
    assert client.post("/api/v1/simulation/nope", headers=AUTH).status_code == 404
    assert client.post("/api/v1/simulation/brute_force").status_code == 401
    assert len(client.get("/api/v1/simulation").json()) == len(SCENARIOS)
    assert client.get("/api/v1/simulation/traffic").json()["enabled"] is False


def test_traffic_toggle(client):
    assert client.post("/api/v1/simulation/traffic", json={"enabled": True}, headers=AUTH).json()["enabled"] is True
    assert client.post("/api/v1/simulation/traffic", json={"enabled": False}, headers=AUTH).json()["enabled"] is False


def test_reset_reseeds(client):
    assert client.post("/api/v1/simulation/reset", headers=AUTH).json()["status"] == "reset"
    assert len(client.get("/api/v1/users").json()) == 25
