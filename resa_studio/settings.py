"""Runtime paths for RESA Studio."""
from __future__ import annotations

import os
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent


def _detect_repo_root(start: Path) -> Path:
    """Walk up from *start* until we find configs/ + pyproject.toml."""
    for candidate in (start, *start.parents):
        if (candidate / "configs").is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate.resolve()
    return start.resolve()


_DEFAULT_ROOT = _detect_repo_root(_PKG_ROOT.parent)


def _repo_root() -> Path:
    env = os.environ.get("RESA_PROJECT_ROOT")
    if env:
        root = Path(env).resolve()
        if (root / "configs").is_dir():
            return root
    return _DEFAULT_ROOT


REPO_ROOT = _repo_root()
OUT_ROOT = Path(os.environ.get("RESA_OUT_ROOT", REPO_ROOT / "out")).resolve()
CONFIGS_ROOT = Path(os.environ.get("RESA_CONFIGS_ROOT", REPO_ROOT / "configs")).resolve()
PROJECTS_ROOT = Path(os.environ.get("RESA_PROJECTS_ROOT", CONFIGS_ROOT / "projects")).resolve()
FRONTEND_DIR = REPO_ROOT / "frontend" / "public"
