"""Aggregates for the overview screen."""
from __future__ import annotations

from fastapi import APIRouter

from ..queries import dashboard_summary
from .deps import DB

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary", summary="KPIs, trends, distributions, map data and recent activity")
def summary(db: DB) -> dict:
    return dashboard_summary(db)
