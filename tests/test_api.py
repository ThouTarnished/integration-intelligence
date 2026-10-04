"""HTTP contract: validation, auth, ingestion and every read endpoint."""
from conftest import AUTH, EVENT


def test_seeded_on_first_start(client):
    assert len(client.get("/api/v1/users").json()) == 25
    assert client.get("/api/v1/events?limit=500").json()["total"] > 300
    assert len(client.get("/api/v1/incidents").json()) > 0


def test_writes_require_api_key(client):
    assert client.post("/api/v1/events", json=EVENT).status_code == 401
    assert client.post("/api/v1/events", json=EVENT, headers={"X-API-Key": "wrong"}).status_code == 401


def test_validation(client):
    assert client.post("/api/v1/events", json={**EVENT, "ip_address": "nope"}, headers=AUTH).status_code == 422
    assert client.post("/api/v1/events", json={**EVENT, "event_type": "x"}, headers=AUTH).status_code == 422
    assert client.post("/api/v1/events", json={**EVENT, "user_id": "bob"}, headers=AUTH).status_code == 422
    assert client.post("/api/v1/events", json={**EVENT, "user_id": "USR-9999"}, headers=AUTH).status_code == 404


def test_ingest_normalizes_scores_and_explains(client):
    body = {**EVENT, "location": "  london ", "device_id": "DEV-7777", "ip_reputation": "suspicious"}
    response = client.post("/api/v1/events", json=body, headers=AUTH)
    assert response.status_code == 201
    out = response.json()
    assert out["event"]["location"] == "London, UK"
    assert {"New device", "Unusual location", "Suspicious IP"} <= set(out["risk"]["signals"])
    assert out["risk"]["contributions"][0]["weight"] == 30
    assert response.headers["X-Request-ID"] and response.headers["X-Response-Time"].endswith("ms")
    event_id = out["event"]["event_id"]
    assert client.get(f"/api/v1/events/{event_id}").json()["user_id"] == "USR-1001"


def test_unknown_ids_are_404(client):
    for path in ("/events/EVT-99999999", "/events/garbage", "/incidents/INC-9999", "/users/USR-9999"):
        assert client.get(f"/api/v1{path}").status_code == 404


def test_event_search_and_filters(client):
    page = client.get("/api/v1/events?risk_level=critical&limit=5").json()
    assert all(e["risk_level"] == "CRITICAL" for e in page["items"]) and len(page["items"]) <= 5
    by_name = client.get("/api/v1/events?q=fenwick").json()
    assert by_name["total"] > 0 and all(e["user_id"] == "USR-1001" for e in by_name["items"])
    oldest = client.get("/api/v1/events?sort=asc&limit=2").json()["items"]
    assert oldest[0]["timestamp"] <= oldest[1]["timestamp"]


def test_users(client):
    users = client.get("/api/v1/users").json()
    assert {"risk_score", "risk_level", "event_count", "open_incidents"} <= users[0].keys()
    profile = client.get("/api/v1/users/usr-1004").json()
    assert profile["user_id"] == "USR-1004" and profile["devices"] and profile["risk_history"]
    assert client.get("/api/v1/users/USR-1004/risk").json()["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def test_incident_triage(client):
    incident = client.get("/api/v1/incidents?status=open").json()[0]
    detail = client.get(f"/api/v1/incidents/{incident['incident_id']}").json()
    assert detail["timeline"] and detail["title"] and isinstance(detail["mitre"], list)
    path = f"/api/v1/incidents/{incident['incident_id']}"
    assert client.patch(path, json={"status": "RESOLVED"}).status_code == 401
    assert client.patch(path, json={"status": "BOGUS"}, headers=AUTH).status_code == 422
    assert client.patch(path, json={"status": "INVESTIGATING"}, headers=AUTH).json()["status"] == "INVESTIGATING"


def test_dashboard_summary(client):
    summary = client.get("/api/v1/dashboard/summary").json()
    assert summary["total_events"] > 0 and len(summary["events_by_day"]) == 7
    assert len(summary["events_by_hour"]) == 24 and len(summary["score_histogram"]) == 21
    assert summary["geo"]["cities"] and all("lat" in c for c in summary["geo"]["cities"])


def test_risk_engine_endpoints(client):
    assert len(client.get("/api/v1/risk/rules").json()["signals"]) >= 10
    result = client.post("/api/v1/risk/evaluate", json={"signals": ["New device", "Suspicious IP"]}).json()
    assert result["risk_score"] == 45
    assert client.post("/api/v1/risk/evaluate", json={"signals": ["Nope"]}).status_code == 422


def test_health_metrics_and_catalog(client):
    health = client.get("/api/v1/integration/health").json()
    assert health["status"] == "CONNECTED" and health["ai_mode"] == "deterministic"
    secured = {e["path"] for e in health["endpoints"] if e["auth"]}
    assert "/api/v1/events" in secured and "/api/v1/incidents/{incident_id}" in secured
    metrics = client.get("/api/v1/integration/metrics").json()
    assert metrics["requests"] > 0 and len(metrics["throughput_per_minute"]) == 30


def test_dashboard_page_and_docs(client):
    page = client.get("/")
    assert page.status_code == 200 and "test-key" in page.text  # demo mode injects the key
    assert client.get("/docs").status_code == 200
    assert client.get("/favicon.ico").status_code == 200


def test_rejects_timestamps_the_engine_cannot_use(client):
    for timestamp in ("2099-01-01T00:00:00", "0001-01-01T00:00:00+01:00", "1999-12-31T23:59:59"):
        assert client.post("/api/v1/events", json={**EVENT, "timestamp": timestamp}, headers=AUTH).status_code == 422


def test_blank_locations_and_malformed_ids_are_client_errors(client):
    assert client.post("/api/v1/events", json={**EVENT, "location": "   "}, headers=AUTH).status_code == 422
    for path in ("/api/v1/incidents/INC-²", "/api/v1/events/EVT-99999999999999999999"):
        assert client.get(path).status_code == 404
