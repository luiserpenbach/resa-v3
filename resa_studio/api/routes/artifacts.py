"""Serve report artifacts from out/."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from resa.paths import safe_run_dirname

from resa_studio.settings import OUT_ROOT

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _run_outdir(engine: str, config_hash: str) -> Path:
    try:
        outdir = (OUT_ROOT / safe_run_dirname(engine, config_hash)).resolve()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not outdir.is_relative_to(OUT_ROOT.resolve()):
        raise HTTPException(status_code=400, detail="invalid run path")
    return outdir


def _safe_artifact_path(engine: str, config_hash: str, filepath: str) -> Path:
    outdir = _run_outdir(engine, config_hash)
    if not outdir.is_dir():
        raise HTTPException(status_code=404, detail="run folder not found")
    target = (outdir / filepath).resolve()
    if not target.is_relative_to(outdir):
        raise HTTPException(status_code=400, detail="invalid artifact path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return target


@router.get("/{engine}/{config_hash}")
def list_artifacts(engine: str, config_hash: str) -> dict[str, list[str]]:
    outdir = _run_outdir(engine, config_hash)
    if not outdir.is_dir():
        raise HTTPException(status_code=404, detail="run folder not found")
    files = sorted(
        p.relative_to(outdir).as_posix() for p in outdir.rglob("*") if p.is_file()
    )
    return {"engine": engine, "config_hash": config_hash, "artifacts": files}


@router.get("/{engine}/{config_hash}/{filepath:path}")
def get_artifact(engine: str, config_hash: str, filepath: str) -> FileResponse:
    target = _safe_artifact_path(engine, config_hash, filepath)
    return FileResponse(target)
