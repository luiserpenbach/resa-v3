"""Compare runs and configs."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from resa_studio.adapters.compare_service import CompareService

router = APIRouter(prefix="/compare", tags=["compare"])
_compare = CompareService()


class CompareRunsBody(BaseModel):
    engine_a: str
    config_hash_a: str
    engine_b: str
    config_hash_b: str


class CompareConfigsBody(BaseModel):
    config_a: dict[str, Any]
    config_b: dict[str, Any]


@router.post("/runs")
def compare_runs(body: CompareRunsBody) -> dict[str, Any]:
    try:
        return _compare.compare_runs(
            body.engine_a,
            body.config_hash_a,
            body.engine_b,
            body.config_hash_b,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/configs")
def compare_configs(body: CompareConfigsBody) -> dict[str, Any]:
    return _compare.compare_configs(body.config_a, body.config_b)
