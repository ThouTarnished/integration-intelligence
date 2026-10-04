"""Natural-language questions about incidents and users."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import analyst
from ..schemas import AskIn
from .deps import DB, rate_limit

router = APIRouter(tags=["ai analyst"])


@router.post("/ai/ask", dependencies=[Depends(rate_limit)], summary="Ask the analyst to explain risk decisions")
def ask(body: AskIn, db: DB) -> dict:
    return analyst.ask(db, body.question)
