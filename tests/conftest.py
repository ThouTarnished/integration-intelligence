"""Test setup: an isolated temporary database and a known API key, configured *before* `iip` is imported."""
import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="iip-tests-"))
os.environ.update(IIP_DB_URL=f"sqlite:///{_TMP / 'test.db'}", IIP_API_KEY="test-key",
                  IIP_RATE_LIMIT_PER_MINUTE="100000", IIP_DEMO_MODE="true",
                  OPENAI_API_KEY="")  # empty, not absent: load_dotenv never overrides an existing variable

AUTH = {"X-API-Key": "test-key"}
EVENT = {"user_id": "USR-1001", "event_type": "login", "ip_address": "203.0.113.9",
         "location": "Dubai, UAE", "device_id": "DEV-2000"}


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from iip.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(client):
    from iip.database import SessionLocal

    with SessionLocal() as session:
        yield session
