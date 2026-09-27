"""Stateless calculation endpoints (/api/calc/*) used by the Studio UI.

Every request carries the complete engine design dict; nothing is written to
disk, so these endpoints also run on serverless hosts. Invalid designs return
422 with ``detail = [{path, message}]``; physics failures return 400.
"""
from __future__ import annotations

import threading
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from resa_studio.adapters import calc_service

router = APIRouter(prefix="/calc", tags=["calc"])


class DesignBody(BaseModel):
    design: dict[str, Any]


class HeatFluxBody(DesignBody):
    wall_temp_K: float = Field(default=800.0, gt=100, lt=4000)
    coolant_pressure_bar: Optional[float] = Field(default=None, gt=0)


class CoolingBody(DesignBody):
    fidelity: Literal["preview", "full"] = "preview"


class GeometryBody(DesignBody):
    x_m: Optional[float] = None


class ExportBody(DesignBody):
    channel_id: int = 0
    format: Literal["stl", "step"] = "stl"


class YamlBody(BaseModel):
    text: str = Field(max_length=2_000_000)


class TradeBody(DesignBody):
    parameter: str
    values: list[float]
    include: list[Literal["heat_flux", "cooling"]] = ["heat_flux"]
    wall_temp_K: float = Field(default=800.0, gt=100, lt=4000)


# The physics stack (rocketcea / NASA CEA Fortran, CoolProp caches) keeps
# process-global state; one calculation at a time per process.
_CALC_LOCK = threading.Lock()


def _call(fn, *args, **kwargs) -> Any:
    try:
        with _CALC_LOCK:
            return fn(*args, **kwargs)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=calc_service.validation_errors(exc)) from exc
    except (ValueError, RuntimeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/catalog")
def catalog() -> dict[str, Any]:
    return calc_service.catalog()


@router.post("/validate")
def validate(body: DesignBody) -> dict[str, Any]:
    return calc_service.validate(body.design)


@router.post("/performance")
def performance(body: DesignBody) -> dict[str, Any]:
    return _call(calc_service.performance, body.design)


@router.post("/heat-flux")
def heat_flux(body: HeatFluxBody) -> dict[str, Any]:
    return _call(calc_service.heat_flux, body.design, body.wall_temp_K, body.coolant_pressure_bar)


@router.post("/cooling")
def cooling(body: CoolingBody) -> dict[str, Any]:
    return _call(calc_service.cooling, body.design, body.fidelity)


@router.post("/cooling/suggest")
def cooling_suggest(body: DesignBody) -> dict[str, Any]:
    return _call(calc_service.suggest_channels, body.design)


@router.post("/cooling/geometry")
def cooling_geometry(body: GeometryBody) -> dict[str, Any]:
    return _call(calc_service.geometry, body.design, body.x_m)


@router.post("/cooling/export")
def cooling_export(body: ExportBody, background: BackgroundTasks) -> FileResponse:
    try:
        path = _call(calc_service.export_channel, body.design, body.channel_id, body.format)
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="STEP export needs cadquery-ocp on the server") from exc
    background.add_task(path.unlink, missing_ok=True)
    media = "model/stl" if body.format == "stl" else "application/step"
    return FileResponse(path, media_type=media, filename=f"channel_{body.channel_id:02d}.{body.format}")


@router.post("/offdesign")
def offdesign(body: DesignBody) -> dict[str, Any]:
    return _call(calc_service.offdesign, body.design)


@router.post("/trade-study")
def trade_study(body: TradeBody) -> dict[str, Any]:
    return _call(calc_service.trade_study, body.design, body.parameter, body.values,
                 tuple(body.include), body.wall_temp_K)


@router.post("/yaml/parse")
def yaml_parse(body: YamlBody) -> dict[str, Any]:
    return _call(calc_service.parse_yaml, body.text)


@router.post("/yaml/dump")
def yaml_dump(body: DesignBody) -> dict[str, Any]:
    return {"text": calc_service.dump_yaml(body.design)}
