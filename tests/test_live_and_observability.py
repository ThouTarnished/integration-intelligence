import asyncio
import json

from iip.live import LiveHub
from iip.observability import Metrics, RateLimiter


def test_hub_fans_out_to_subscribers():
    async def scenario() -> list[str]:
        hub = LiveHub()
        hub.bind(asyncio.get_running_loop())
        stream = hub.stream(heartbeat=5)
        assert "connected" in await anext(stream)
        hub.publish("event", {"event_id": "EVT-00001"})
        message = await asyncio.wait_for(anext(stream), timeout=1)
        await stream.aclose()
        return [message, hub.clients]

    message, clients_after_close = asyncio.run(scenario())
    assert "event: event" in message and json.loads(message.split("data: ")[1])["event_id"] == "EVT-00001"
    assert clients_after_close == 0


def test_publish_without_subscribers_is_a_no_op():
    LiveHub().publish("event", {"x": 1})  # no loop bound, nobody listening: must not raise


def test_rate_limiter_token_bucket():
    limiter = RateLimiter(per_minute=3)
    assert [limiter.hit("a") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert limiter.hit("a") > 0          # bucket empty: told how long to wait
    assert limiter.hit("b") == 0.0       # buckets are per client


def test_metrics_percentiles_and_throughput():
    metrics = Metrics()
    for ms in range(1, 101):
        metrics.observe("GET", "/events", 200 if ms < 100 else 500, float(ms))
    metrics.record_ingest(4)
    snap = metrics.snapshot()
    assert snap["requests"] == 100 and snap["errors"] == 1
    assert snap["latency_ms"]["p50"] == 51.0 and snap["latency_ms"]["p99"] == 100.0
    assert snap["throughput_per_minute"][-1] == 4


def test_odd_request_ids_are_replaced_and_unknown_paths_share_one_metric(client):
    response = client.get("/api/v1/integration/health", headers={"X-Request-ID": b"caf\xe9"})
    assert response.status_code == 200 and response.headers["X-Request-ID"] != "caf\xe9"
    for n in range(3):
        client.get(f"/api/v1/no-such-route/{n}")
    routes = [r["route"] for r in client.get("/api/v1/integration/metrics").json()["routes"]]
    assert not any("no-such-route" in route for route in routes)
