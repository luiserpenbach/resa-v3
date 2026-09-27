"""Pick the workspace backend from the environment.

    RESA_WORKSPACE_DB / DATABASE_URL / POSTGRES_URL  → SqlStore
    VERCEL (read-only serverless filesystem)          → no storage
    otherwise                                         → FileStore at RESA_WORKSPACE_DIR or <repo>/workspace
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .store import WorkspaceStore

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE_DIR = REPO_ROOT / "workspace"
DB_ENV_VARS = ("RESA_WORKSPACE_DB", "DATABASE_URL", "POSTGRES_URL")


def database_url() -> str | None:
    for var in DB_ENV_VARS:
        value = os.environ.get(var, "").strip()
        if value:
            return value
    return None


def _folder_label(root: Path) -> str:
    try:
        return f"{root.resolve().relative_to(REPO_ROOT).as_posix()}/ folder"
    except ValueError:
        return str(root)


@lru_cache(maxsize=1)
def get_store() -> WorkspaceStore | None:
    """The configured store (cached), or None when no storage is available."""
    url = database_url()
    if url:
        from .sql_store import SqlStore

        return SqlStore(url)
    if os.environ.get("VERCEL"):
        return None
    from .file_store import FileStore

    root = Path(os.environ.get("RESA_WORKSPACE_DIR") or DEFAULT_WORKSPACE_DIR)
    return FileStore(root, label=_folder_label(root))


def reset_store_cache() -> None:
    get_store.cache_clear()
