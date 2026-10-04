"""Single source of "now". Timestamps are stored as naive UTC throughout the database."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
