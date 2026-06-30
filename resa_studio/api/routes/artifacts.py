"""Serve report artifacts from out/."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from resa_studio.settings import OUT_ROOT

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _safe_artifact_path(engine: str, config_hash: str, filepath: str) -> Path:
    outdir = (OUT_ROOT / f"{engine}_{config_hash}").resolve()
    if not outdir.is_dir():
        raise HTTPException(status_code=404, detail="run folder not found")
    target = (outdir / filepath).resolve()
    if not str(target).startswith(str(outdir)):
        raise HTTPException(status_code=400, detail="invalid artifact path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return target


@router.get("/{engine}/{config_hash}")
def list_artifacts(engine: str, config_hash: str) -> dict[str, list[str]]:
    outdir = (OUT_ROOT / f"{engine}_{config_hash}").resolve()
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
