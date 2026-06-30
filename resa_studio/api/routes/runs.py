"""Run pipeline endpoints."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from resa_studio.adapters.config_service import ConfigService
from resa_studio.adapters.run_service import RunService

router = APIRouter(prefix="/runs", tags=["runs"])
_runs = RunService()
_configs = ConfigService()


class RunRequest(BaseModel):
    config_path: str | None = None
    config: dict[str, Any] | None = None


class RunResponse(BaseModel):
    mode: Literal["fast", "full"]
    engine: str
    config_hash: str
    config_path: str | None
    outdir: str | None
    summary: dict[str, Any]
    warnings: list[str]
    provenance: dict[str, str]
    artifacts: list[str]
    result: dict[str, Any]


def _run_output(out) -> RunResponse:
    return RunResponse(
        mode=out.mode,
        engine=out.config.engine,
        config_hash=out.config.config_hash,
        config_path=out.config_path,
        outdir=str(out.outdir.relative_to(_runs.repo_root)).replace("\\", "/")
        if out.outdir else None,
        summary=out.result["summary"],
        warnings=out.result["warnings"],
        provenance=out.result["provenance"],
        artifacts=list(out.artifacts),
        result=out.result,
    )


class RunListItem(BaseModel):
    engine: str
    config_hash: str
    outdir: str
    mode: str
    thrust_N: float | None
    isp_s: float | None
    modified_at: float


@router.get("", response_model=list[RunListItem])
def list_runs() -> list[RunListItem]:
    return [RunListItem(**item) for item in _runs.list_runs()]


@router.post("/fast", response_model=RunResponse)
def run_fast(body: RunRequest) -> RunResponse:
    try:
        out = _runs.run_fast(config_path=body.config_path, config=body.config)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_configs.format_validation_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _run_output(out)


@router.post("/full", response_model=RunResponse)
def run_full(body: RunRequest) -> RunResponse:
    try:
        out = _runs.run_full(config_path=body.config_path, config=body.config)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_configs.format_validation_error(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _run_output(out)


@router.get("/{engine}/{config_hash}")
def get_run(engine: str, config_hash: str) -> dict[str, Any]:
    data = _runs.load_existing(engine, config_hash)
    if data is None:
        raise HTTPException(status_code=404, detail="run not found")
    return data
