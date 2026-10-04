"""The rulebook and the what-if scorer behind the Risk Lab."""
from __future__ import annotations

from fastapi import APIRouter

from .. import rules
from ..schemas import EvaluateIn

router = APIRouter(tags=["risk engine"])


@router.get("/risk/rules", summary="Every signal, weight, ATT&CK mapping, level and threshold")
def get_rules() -> dict:
    return rules.rulebook()


@router.post("/risk/evaluate", summary="Dry-run: score a hand-picked set of signals (nothing is stored)")
def evaluate(body: EvaluateIn) -> dict:
    return rules.what_if(body.signals)
