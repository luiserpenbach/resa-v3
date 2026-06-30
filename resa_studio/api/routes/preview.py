"""Live preview endpoints for the design workspace."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from resa_studio.adapters import preview_service

router = APIRouter(prefix="/preview", tags=["preview"])


class ConfigBody(BaseModel):
    config: dict[str, Any]


class CoolingSectionBody(ConfigBody):
    x_m: float | None = None


class Cooling3DBody(ConfigBody):
    channel_id: int = 0


class ExportChannelBody(ConfigBody):
    channel_id: int = 0
    format: Literal["stl", "step"] = "stl"


@router.get("/cache/stats")
def preview_cache_stats() -> dict[str, Any]:
    return preview_service.preview_cache_stats()


@router.post("/regen/thermal")
def regen_thermal(body: ConfigBody) -> dict[str, Any]:
    try:
        return preview_service.preview_regen_thermal(body.config)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=preview_service.format_validation_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/contour")
def preview_contour(body: ConfigBody) -> dict[str, Any]:
    try:
        return preview_service.preview_contour(body.config)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=preview_service.format_validation_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cooling/suggest-channels")
def suggest_channels(body: ConfigBody) -> dict[str, Any]:
    try:
        return preview_service.suggest_n_channels(body.config)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=preview_service.format_validation_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cooling/section")
def cooling_section(body: CoolingSectionBody) -> dict[str, Any]:
    try:
        return preview_service.preview_cooling_section(body.config, body.x_m)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=preview_service.format_validation_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cooling/3d")
def cooling_3d(body: Cooling3DBody) -> dict[str, Any]:
    try:
        return preview_service.preview_cooling_3d(body.config, body.channel_id)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=preview_service.format_validation_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cooling/export-channel")
def export_channel(body: ExportChannelBody) -> FileResponse:
    try:
        path = preview_service.export_channel(body.config, body.channel_id, body.format)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=preview_service.format_validation_error(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    media = "model/stl" if body.format == "stl" else "application/step"
    return FileResponse(path, media_type=media, filename=path.name)
