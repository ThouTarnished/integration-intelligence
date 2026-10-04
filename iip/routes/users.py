"""Customer risk profiles."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..database import User
from ..queries import user_detail, user_risk, users_overview
from .deps import DB

router = APIRouter(tags=["users"])


def _user_or_404(db: DB, user_id: str) -> User:
    user = db.get(User, user_id.upper())
    if user is None:
        raise HTTPException(404, "User not found")
    return user


@router.get("/users", summary="Every customer with current risk and activity counts")
def list_users(db: DB) -> list[dict]:
    return users_overview(db)


@router.get("/users/{user_id}", summary="Customer profile: devices, locations, risk history, incidents")
def get_user(user_id: str, db: DB) -> dict:
    return user_detail(db, _user_or_404(db, user_id))


@router.get("/users/{user_id}/risk", summary="A customer's current risk decision")
def get_user_risk(user_id: str, db: DB) -> dict:
    return user_risk(db, _user_or_404(db, user_id).id)
