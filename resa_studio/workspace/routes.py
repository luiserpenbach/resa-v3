"""Workspace HTTP API — mount with ``app.include_router(router)``."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from .config import get_store
from .examples import example_bundles, examples_available, import_examples
from .store import (
    MAX_DESCRIPTION,
    MAX_MESSAGE,
    MAX_NAME,
    Conflict,
    Invalid,
    NotFound,
    TooLarge,
    WorkspaceStore,
)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

_NO_STORAGE = (
    "No server-side workspace storage configured — set RESA_WORKSPACE_DB / DATABASE_URL "
    "to a PostgreSQL database, or run RESA Studio locally to use the workspace/ folder."
)

Status = Literal["concept", "preliminary", "detailed", "frozen"]
Pid = Annotated[str, Path(description="Project id")]
Did = Annotated[str, Path(description="Design id")]
Num = Annotated[int, Path(ge=1, description="Version number")]


def require_store() -> WorkspaceStore:
    store = get_store()
    if store is None:
        raise HTTPException(status_code=503, detail=_NO_STORAGE)
    return store


Store = Annotated[WorkspaceStore, Depends(require_store)]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Conflict as exc:
        raise HTTPException(
            status_code=409, detail={"message": str(exc), "current_revision": exc.current_revision},
        ) from exc
    except TooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Invalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class CreateProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME)
    description: str = Field(default="", max_length=MAX_DESCRIPTION)
    author: str | None = None


class UpdateProjectBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)


class DerivedFromBody(BaseModel):
    design_id: str
    version: int | None = Field(default=None, ge=1)


class CreateDesignBody(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME)
    description: str = Field(default="", max_length=MAX_DESCRIPTION)
    config: dict[str, Any] | None = None
    author: str | None = None
    derived_from: DerivedFromBody | None = None


class UpdateDesignBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    status: Status | None = None
    is_baseline: bool | None = None
    author: str | None = None


class DraftBody(BaseModel):
    config: dict[str, Any]
    revision: int
    author: str | None = None


class CreateVersionBody(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE)
    author: str | None = None
    kpis: dict[str, Any] | None = None


class AuthorBody(BaseModel):
    author: str | None = None


class ImportBody(BaseModel):
    bundle: dict[str, Any]
    author: str | None = None


@router.get("/info")
def info() -> dict[str, Any]:
    store = get_store()
    if store is None:
        return {"storage": "none", "writable": False, "location": "",
                "examples_available": examples_available()}
    return {
        "storage": store.kind,
        "writable": store.writable,
        "location": store.location,
        "examples_available": examples_available(),
    }


# ── projects ─────────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects(store: Store) -> list[dict[str, Any]]:
    with _errors():
        return store.list_projects()


@router.post("/projects", status_code=201)
def create_project(body: CreateProjectBody, store: Store) -> dict[str, Any]:
    with _errors():
        return store.create_project(body.name, body.description, body.author)


@router.get("/projects/{pid}")
def get_project(pid: Pid, store: Store) -> dict[str, Any]:
    with _errors():
        return {"project": store.get_project(pid), "designs": store.list_designs(pid)}


@router.patch("/projects/{pid}")
def update_project(pid: Pid, body: UpdateProjectBody, store: Store) -> dict[str, Any]:
    with _errors():
        return store.update_project(pid, name=body.name, description=body.description)


@router.delete("/projects/{pid}")
def delete_project(pid: Pid, store: Store) -> dict[str, bool]:
    with _errors():
        store.delete_project(pid)
    return {"ok": True}


@router.get("/projects/{pid}/export")
def export_project(pid: Pid, store: Store) -> dict[str, Any]:
    with _errors():
        return store.export_project(pid)


# ── designs ──────────────────────────────────────────────────────────────────

@router.post("/projects/{pid}/designs", status_code=201)
def create_design(pid: Pid, body: CreateDesignBody, store: Store) -> dict[str, Any]:
    with _errors():
        return store.create_design(
            pid,
            body.name,
            description=body.description,
            config=body.config,
            author=body.author,
            derived_from=body.derived_from.model_dump() if body.derived_from else None,
        )


@router.get("/projects/{pid}/designs/{did}")
def get_design(pid: Pid, did: Did, store: Store) -> dict[str, Any]:
    with _errors():
        return store.get_design(pid, did)


@router.patch("/projects/{pid}/designs/{did}")
def update_design(pid: Pid, did: Did, body: UpdateDesignBody, store: Store) -> dict[str, Any]:
    with _errors():
        return store.update_design(
            pid,
            did,
            name=body.name,
            description=body.description,
            status=body.status,
            is_baseline=body.is_baseline,
            author=body.author,
        )


@router.put("/projects/{pid}/designs/{did}/draft")
def save_draft(pid: Pid, did: Did, body: DraftBody, store: Store) -> dict[str, Any]:
    with _errors():
        return store.save_draft(pid, did, body.config, body.revision, body.author)


@router.delete("/projects/{pid}/designs/{did}")
def delete_design(pid: Pid, did: Did, store: Store) -> dict[str, bool]:
    with _errors():
        store.delete_design(pid, did)
    return {"ok": True}


# ── versions ─────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/designs/{did}/versions")
def list_versions(pid: Pid, did: Did, store: Store) -> list[dict[str, Any]]:
    with _errors():
        return store.list_versions(pid, did)


@router.post("/projects/{pid}/designs/{did}/versions", status_code=201)
def create_version(pid: Pid, did: Did, body: CreateVersionBody, store: Store) -> dict[str, Any]:
    with _errors():
        return store.create_version(pid, did, body.message, body.author, body.kpis)


@router.get("/projects/{pid}/designs/{did}/versions/{n}")
def get_version(pid: Pid, did: Did, n: Num, store: Store) -> dict[str, Any]:
    with _errors():
        return store.get_version(pid, did, n)


@router.post("/projects/{pid}/designs/{did}/versions/{n}/restore")
def restore_version(
    pid: Pid, did: Did, n: Num, store: Store, body: AuthorBody | None = None,
) -> dict[str, Any]:
    with _errors():
        return store.restore_version(pid, did, n, body.author if body else None)


# ── bundles / examples ───────────────────────────────────────────────────────

@router.post("/import", status_code=201)
def import_bundle(body: ImportBody, store: Store) -> dict[str, Any]:
    with _errors():
        return store.import_bundle(body.bundle, body.author)


@router.post("/examples")
def import_example_projects(store: Store, body: AuthorBody | None = None) -> list[dict[str, Any]]:
    with _errors():
        return import_examples(store, body.author if body else None)


@router.get("/examples/bundles")
def get_example_bundles() -> list[dict[str, Any]]:
    """Example projects as import bundles — works without server storage."""
    return example_bundles()
