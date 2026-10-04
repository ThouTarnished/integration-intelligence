"""Real-time layer.

* `LiveHub` fans server events out to every browser connected to the Server-Sent Events
  stream. `publish` is safe to call from worker threads (sync FastAPI endpoints run in a
  thread pool) because it hands each message to the event loop via call_soon_threadsafe.
* `TrafficGenerator` is an optional background task that produces a steady trickle of
  realistic activity (with the occasional attack) so a demo dashboard feels alive.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import random
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import rules
from .clock import utcnow
from .database import Device, Event, Incident, SessionLocal, User
from .observability import metrics
from .pipeline import process_event
from .queries import event_dict, incidents_page
from .seed import ATTACKS, plan_scenario, routine_event

log = logging.getLogger("iip.live")


class LiveHub:
    def __init__(self, queue_size: int = 256) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queues: set[asyncio.Queue[str]] = set()
        self._queue_size = queue_size
        self._ids = itertools.count(1)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def clients(self) -> int:
        return len(self._queues)

    def publish(self, kind: str, data: dict) -> None:
        if self._loop is None or not self._queues:
            return
        message = f"id: {next(self._ids)}\nevent: {kind}\ndata: {json.dumps(data, default=str)}\n\n"
        with suppress(RuntimeError):  # loop already closed during shutdown
            self._loop.call_soon_threadsafe(self._fan_out, message)

    def _fan_out(self, message: str) -> None:
        for queue in list(self._queues):
            if queue.full():  # slow client: drop its oldest message rather than block everyone
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(message)

    async def stream(self, heartbeat: float = 15.0) -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_size)
        self._queues.add(queue)
        try:
            yield "retry: 3000\n: connected\n\n"
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self._queues.discard(queue)


hub = LiveHub()


def broadcast(db: Session, events: list[Event], source: str) -> None:
    """Publish freshly processed events, plus the incidents they touched."""
    for event in events:
        hub.publish("event", {"source": source, "event": event_dict(event)})
    touched = {e.incident_id for e in events if e.incident_id}
    if touched:
        for incident in incidents_page(db, select(Incident).where(Incident.id.in_(touched))):
            hub.publish("incident", incident)


class TrafficGenerator:
    def __init__(self, attack_ratio: float = 0.06) -> None:
        self.attack_ratio = attack_ratio
        self.generated = 0
        self.started_at: datetime | None = None
        self._task: asyncio.Task | None = None
        self._ticking: asyncio.Future | None = None
        self._last_transaction: dict[str, datetime] = {}

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict:
        return {"enabled": self.running, "generated": self.generated,
                "started_at": self.started_at.isoformat() if self.started_at and self.running else None}

    async def start(self) -> None:
        if not self.running:
            self.started_at = utcnow()
            self._task = asyncio.create_task(self._run(), name="iip-live-traffic")
            hub.publish("traffic", self.status())

    async def stop(self) -> None:
        task, self._task = self._task, None  # cleared first, so a start() during the wait gets a task of its own
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        # A tick already running in a worker thread can't be interrupted, so wait for it: a reset must not race it.
        if (tick := self._ticking) is not None:
            self._ticking = None
            try:
                await tick
            except Exception:
                log.exception("Live traffic tick failed")
        hub.publish("traffic", self.status())

    async def _run(self) -> None:
        rnd = random.Random()
        while True:
            await asyncio.sleep(rnd.uniform(1.0, 2.8))
            self._ticking = asyncio.ensure_future(run_in_threadpool(self._tick, rnd))
            try:
                await asyncio.shield(self._ticking)  # cancelling the loop must not abandon a tick halfway
            except Exception:  # keep generating even if one tick fails
                log.exception("Live traffic tick failed")
            self._ticking = None

    def _tick(self, rnd: random.Random) -> None:
        with SessionLocal() as db:
            users = db.scalars(select(User)).all()
            user = rnd.choice(users)
            devices = db.scalars(select(Device.id).where(Device.user_id == user.id, Device.trusted)).all()
            now = utcnow()
            if rnd.random() < self.attack_ratio:
                payloads = plan_scenario(rnd.choice(ATTACKS), user, devices[0], users, now, rnd)
            else:
                # Real customers do not transact every few seconds; avoid false "Rapid transactions".
                recent = self._last_transaction.get(user.id)
                allow = recent is None or now - recent > rules.RAPID_TRANSACTION_WINDOW
                payloads = [routine_event(user, rnd.choice(devices), now, rnd, allow_transaction=allow)]
            events = [process_event(db, payload)[0] for payload in payloads]
            for event in events:
                if event.event_type == "transaction":
                    self._last_transaction[user.id] = event.timestamp
            self.generated += len(events)
            metrics.record_ingest(len(events))
            broadcast(db, events, source="traffic")


traffic = TrafficGenerator()
