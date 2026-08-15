"""Config validation and schema endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from resa_studio.adapters.config_service import ConfigConflictError, ConfigService

router = APIRouter(prefix="/config", tags=["config"])
_configs = ConfigService()


class ConfigPathRequest(BaseModel):
    config_path: str


class ConfigDictRequest(BaseModel):
    config: dict[str, Any]


class ConfigValidateResponse(BaseModel):
    ok: bool
    engine: str
    mode: str
    config_hash: str
    config_path: str | None = None


class ConfigSaveRequest(BaseModel):
    config_path: str
    config: dict[str, Any]
    expected_file_sha256: str | None = None


class ConfigSaveResponse(BaseModel):
    ok: bool
    config_path: str
    source_path: str
    engine: str
    mode: str
    config_hash: str
    file_sha256: str | None = None
    created_override: bool = False


@router.get("/schema")
def get_schema() -> dict[str, Any]:
    return _configs.schema()


@router.get("/resolve")
def resolve_config(config_path: str) -> dict[str, Any]:
    try:
        return _configs.resolve_path(config_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_configs.format_validation_error(exc)) from exc


@router.post("/resolve/path")
def resolve_config_path(body: ConfigPathRequest) -> dict[str, Any]:
    """Same as GET /resolve; useful when query strings are awkward."""
    try:
        return _configs.resolve_path(body.config_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_configs.format_validation_error(exc)) from exc


@router.get("/list")
def list_configs() -> list[dict[str, str]]:
    return _configs.list_configs()


@router.post("/validate/path", response_model=ConfigValidateResponse)
def validate_path(body: ConfigPathRequest) -> ConfigValidateResponse:
    try:
        cfg = _configs.validate_path(body.config_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_configs.format_validation_error(exc)) from exc
    return ConfigValidateResponse(
        ok=True,
        engine=cfg.engine,
        mode=cfg.mode,
        config_hash=cfg.config_hash,
        config_path=body.config_path,
    )


@router.post("/validate", response_model=ConfigValidateResponse)
def validate_dict(body: ConfigDictRequest) -> ConfigValidateResponse:
    try:
        cfg = _configs.validate_dict(body.config)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_configs.format_validation_error(exc)) from exc
    return ConfigValidateResponse(
        ok=True,
        engine=cfg.engine,
        mode=cfg.mode,
        config_hash=cfg.config_hash,
    )


@router.post("/save", response_model=ConfigSaveResponse)
def save_config(body: ConfigSaveRequest) -> ConfigSaveResponse:
    try:
        out = _configs.save_config(
            body.config_path,
            body.config,
            expected_file_sha256=body.expected_file_sha256,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_configs.format_validation_error(exc)) from exc
    return ConfigSaveResponse(**out)
