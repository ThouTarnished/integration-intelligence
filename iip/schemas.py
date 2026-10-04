"""Request bodies. Pydantic validates and normalizes untrusted input before it reaches the engine."""
from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import rules
from .clock import utcnow

EXAMPLE_EVENT = {
    "user_id": "USR-1001", "event_type": "login", "ip_address": "203.0.113.45", "location": "Dubai, UAE",
    "device_id": "DEV-9001", "device_new": True, "failed_attempts": 5, "ip_reputation": "suspicious",
}
# Event times the engine can reason about: nothing before 2000 (older dates overflow when windows are subtracted)
# and at most five minutes ahead of the server clock, allowing for skew.
EARLIEST = datetime(2000, 1, 1)
CLOCK_SKEW = timedelta(minutes=5)


class EventIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, json_schema_extra={"examples": [EXAMPLE_EVENT]})

    user_id: str = Field(pattern=r"^USR-\d+$")
    event_type: Literal["login", "transaction", "resource_access", "password_reset"]
    timestamp: datetime | None = None
    ip_address: str
    location: str = Field(min_length=2, max_length=80)
    device_id: str = Field(pattern=r"^DEV-\d+$")
    device_new: bool | None = None
    failed_attempts: int = Field(0, ge=0, le=100)
    ip_reputation: Literal["clean", "suspicious", "malicious"] = "clean"
    transaction_amount: float | None = Field(None, ge=0, le=1e9)
    resource_accessed: str | None = Field(None, max_length=80)
    status: Literal["success", "failure"] = "success"

    @field_validator("ip_address")
    @classmethod
    def _valid_ip(cls, value: str) -> str:
        try:
            return str(ipaddress.ip_address(value.strip()))
        except ValueError:
            raise ValueError("invalid IP address") from None

    @field_validator("timestamp")
    @classmethod
    def _naive_utc(cls, value: datetime | None) -> datetime | None:
        """Naive UTC (see clock.py), within the range the engine can reason about."""
        if value is None:
            return None
        try:
            value = value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
        except OverflowError:  # e.g. year 1 shifted by a +01:00 offset
            raise ValueError("timestamp out of range") from None
        if not EARLIEST <= value <= utcnow() + CLOCK_SKEW:
            raise ValueError(f"timestamp must be after {EARLIEST:%Y-%m-%d} and at most "
                             f"{rules.minutes(CLOCK_SKEW)} minutes in the future")
        return value


class StatusIn(BaseModel):
    status: Literal["OPEN", "INVESTIGATING", "RESOLVED"]


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class EvaluateIn(BaseModel):
    signals: list[str] = Field(default_factory=list, max_length=len(rules.SIGNALS))

    @field_validator("signals")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        unknown = [s for s in value if s not in rules.SIGNALS]
        if unknown:
            raise ValueError(f"unknown signal(s): {', '.join(unknown)}")
        return value


class TrafficIn(BaseModel):
    enabled: bool
