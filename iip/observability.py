"""Operational plumbing: request IDs, access logs, latency/throughput metrics and rate limiting.

These are the numbers an integration team watches (SLIs): how many calls a client makes,
how fast we answer (p50/p95/p99), how many fail, and how many events flow per minute.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import Counter, deque

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("iip.http")
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")  # request ids we are willing to echo back


class Metrics:
    def __init__(self, window: int = 2000) -> None:
        self._lock = threading.Lock()
        self.started = time.time()
        self.requests = 0
        self.errors = 0
        self.status_classes: Counter[str] = Counter()
        self.routes: dict[str, dict] = {}
        self.latencies: deque[float] = deque(maxlen=window)
        self.ingested: Counter[int] = Counter()  # epoch minute -> events ingested

    def observe(self, method: str, route: str, status: int, millis: float) -> None:
        with self._lock:
            self.requests += 1
            self.errors += status >= 500
            self.status_classes[f"{status // 100}xx"] += 1
            self.latencies.append(millis)
            stats = self.routes.setdefault(f"{method} {route}", {"count": 0, "errors": 0, "total_ms": 0.0})
            stats["count"] += 1
            stats["errors"] += status >= 400
            stats["total_ms"] += millis

    def record_ingest(self, count: int = 1) -> None:
        minute = int(time.time() // 60)
        with self._lock:
            self.ingested[minute] += count
            for old in [m for m in self.ingested if m < minute - 60]:
                del self.ingested[old]

    def snapshot(self) -> dict:
        with self._lock:
            ordered = sorted(self.latencies)
            routes = [{"route": name, "count": s["count"], "errors": s["errors"],
                       "avg_ms": round(s["total_ms"] / s["count"], 2)} for name, s in self.routes.items()]
            minute = int(time.time() // 60)
            throughput = [self.ingested.get(minute - k, 0) for k in range(29, -1, -1)]
            requests, errors, classes = self.requests, self.errors, dict(self.status_classes)

        def pct(p: float) -> float:
            return round(ordered[min(len(ordered) - 1, int(p * len(ordered)))], 2) if ordered else 0.0

        return {
            "uptime_seconds": int(time.time() - self.started),
            "requests": requests,
            "errors": errors,
            "error_rate": round(errors / requests, 4) if requests else 0.0,
            "status_classes": classes,
            "latency_ms": {"p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99),
                           "avg": round(sum(ordered) / len(ordered), 2) if ordered else 0.0},
            "throughput_per_minute": throughput,
            "routes": sorted(routes, key=lambda r: -r["count"])[:12],
        }


metrics = Metrics()


class RequestContextMiddleware:
    """Pure ASGI middleware: tags every response with X-Request-ID / X-Response-Time,
    logs one line per API call and feeds `Metrics`. (Pure ASGI rather than
    BaseHTTPMiddleware so the long-lived SSE stream passes straight through.)"""

    def __init__(self, app: ASGIApp, registry: Metrics = metrics) -> None:
        self.app = app
        self.metrics = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or {}).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_ID.fullmatch(incoming) else uuid.uuid4().hex[:12]
        start = time.perf_counter()
        status = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Response-Time"] = f"{(time.perf_counter() - start) * 1000:.1f}ms"
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            path = scope.get("path", "")
            if path.startswith("/api/") and not path.endswith("/stream"):
                millis = (time.perf_counter() - start) * 1000
                route = getattr(scope.get("route"), "path", None) or "(unmatched)"
                self.metrics.observe(scope["method"], route, status, millis)
                log.info("%s %s -> %s in %.1fms [%s]", scope["method"], path, status, millis, request_id)


class RateLimiter:
    """Token bucket per client: `per_minute` requests a minute, bursting up to `per_minute`."""

    def __init__(self, per_minute: int) -> None:
        self.capacity = float(max(per_minute, 1))
        self.refill_per_second = self.capacity / 60
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> float:
        """Consume a token. Returns 0 when allowed, else the seconds until a token frees up."""
        now = time.monotonic()
        with self._lock:
            if len(self._buckets) > 10_000:  # forget idle clients: a bucket untouched for a minute is full again
                self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < 60}
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_second)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return 0.0
            self._buckets[key] = (tokens, now)
            return (1 - tokens) / self.refill_per_second
