"""Project CRUD and config creation under configs/projects/."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resa_studio.adapters.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])
_projects = ProjectService()


class CreateProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str | None = None
    description: str = ""
    engine: str | None = None


class CreateConfigBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    mode: Literal["design", "analyze"] = "design"
    engine: str | None = None


@router.get("/list")
def list_projects() -> list[dict[str, Any]]:
    return _projects.list_projects()


@router.get("/{slug}")
def get_project(slug: str) -> dict[str, Any]:
    try:
        return _projects.get_project(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/create")
def create_project(body: CreateProjectBody) -> dict[str, Any]:
    try:
        return _projects.create_project(
            body.name,
            slug=body.slug,
            description=body.description,
            engine=body.engine,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{slug}/configs")
def create_config(slug: str, body: CreateConfigBody) -> dict[str, Any]:
    try:
        return _projects.create_config(
            slug,
            body.name,
            mode=body.mode,
            engine=body.engine,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
