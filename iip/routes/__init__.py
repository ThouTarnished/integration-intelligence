"""HTTP API, one module per domain, all mounted under /api/v1."""
from fastapi import APIRouter

from . import analyst, dashboard, events, incidents, risk, simulation, system, users

api_router = APIRouter(prefix="/api/v1")
for module in (events, users, incidents, dashboard, risk, simulation, analyst, system):
    api_router.include_router(module.router)
