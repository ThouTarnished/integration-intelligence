"""Persistence layer: SQLAlchemy 2.0 typed models and the session factory.

SQLite is the default (zero setup); any SQLAlchemy URL can be supplied via IIP_DB_URL.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import DATA_DIR, settings

IS_SQLITE = settings.database_url.startswith("sqlite")
if IS_SQLITE:
    DATA_DIR.mkdir(exist_ok=True)

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if IS_SQLITE else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _record) -> None:
    """WAL lets the live-traffic writer and dashboard readers work side by side; FKs keep rows honest."""
    if IS_SQLITE:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    home_location: Mapped[str] = mapped_column(String(80))
    segment: Mapped[str] = mapped_column(String(20))


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    trusted: Mapped[bool] = mapped_column(default=False)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True, default="OPEN")
    severity: Mapped[str] = mapped_column(String(10), default="LOW")
    risk_score: Mapped[int] = mapped_column(default=0)
    signals: Mapped[list[str]] = mapped_column(JSON, default=list)
    action: Mapped[str] = mapped_column(String(80), default="")
    created: Mapped[datetime] = mapped_column(DateTime)
    updated: Mapped[datetime] = mapped_column(DateTime, index=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_user_time", "user_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(20), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    ip_address: Mapped[str] = mapped_column(String(45), index=True)
    location: Mapped[str] = mapped_column(String(80))
    device_id: Mapped[str] = mapped_column(String(16))
    device_new: Mapped[bool]
    failed_attempts: Mapped[int] = mapped_column(default=0)
    ip_reputation: Mapped[str] = mapped_column(String(12))
    transaction_amount: Mapped[float | None]
    resource_accessed: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(10))
    risk_score: Mapped[int]
    risk_level: Mapped[str] = mapped_column(String(10), index=True)
    signals: Mapped[list[str]] = mapped_column(JSON)
    contributions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    action: Mapped[str] = mapped_column(String(80))
    explanation: Mapped[str] = mapped_column(Text)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), index=True)


class RiskSignal(Base):
    """One row per signal raised on an event — a narrow table that makes analytics queries cheap."""

    __tablename__ = "risk_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    name: Mapped[str] = mapped_column(String(48), index=True)
    weight: Mapped[int]


def init_db() -> None:
    Base.metadata.create_all(engine)


def reset_db() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    with SessionLocal() as session:
        yield session
