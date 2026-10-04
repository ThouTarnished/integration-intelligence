"""Runtime configuration.

Every setting is read once, here, from environment variables (optionally loaded from
a `.env` file in the project root). The rest of the code imports `settings` instead
of calling `os.getenv` all over the place.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "web"
DATA_DIR = ROOT_DIR / "data"

load_dotenv(ROOT_DIR / ".env")


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.getenv(name, default).split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    api_key: str
    database_url: str
    cors_origins: tuple[str, ...]
    demo_mode: bool
    rate_limit_per_minute: int
    openai_api_key: str | None
    openai_model: str
    openai_base_url: str
    host: str
    port: int


def load_settings() -> Settings:
    return Settings(
        api_key=os.getenv("IIP_API_KEY", "demo-key-change-me"),
        database_url=os.getenv("IIP_DB_URL", f"sqlite:///{DATA_DIR / 'iip.db'}"),
        cors_origins=_csv("IIP_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"),
        demo_mode=_flag("IIP_DEMO_MODE", True),
        rate_limit_per_minute=int(os.getenv("IIP_RATE_LIMIT_PER_MINUTE", "240")),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        host=os.getenv("IIP_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )


settings = load_settings()
