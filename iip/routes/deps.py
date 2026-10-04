"""Shared FastAPI dependencies: database session, API-key auth and rate limiting."""
from __future__ import annotations

import math
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_session
from ..observability import RateLimiter

DB = Annotated[Session, Depends(get_session)]
limiter = RateLimiter(settings.rate_limit_per_minute)


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    # compare_digest takes the same time whether the first or last byte differs (no timing leak).
    if not secrets.compare_digest((x_api_key or "").encode(), settings.api_key.encode()):
        raise HTTPException(401, "Invalid or missing X-API-Key")


def rate_limit(request: Request) -> None:
    retry_after = limiter.hit(request.client.host if request.client else "unknown")
    if retry_after:
        raise HTTPException(429, "Rate limit exceeded, slow down", headers={"Retry-After": str(math.ceil(retry_after))})


# Every endpoint that changes state: throttled first (so key guessing is throttled too), then authenticated.
WRITE = [Depends(rate_limit), Depends(require_api_key)]
