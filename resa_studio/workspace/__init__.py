"""Team workspace: projects of engine designs with version history.

Backends: FileStore (git-friendly YAML tree) and SqlStore (SQLite / PostgreSQL),
selected from the environment by get_store(). HTTP API in .routes.
"""
from __future__ import annotations

from .config import get_store, reset_store_cache
from .store import Conflict, Invalid, NotFound, TooLarge, WorkspaceError, WorkspaceStore

__all__ = [
    "Conflict",
    "Invalid",
    "NotFound",
    "TooLarge",
    "WorkspaceError",
    "WorkspaceStore",
    "get_store",
    "reset_store_cache",
]
