"""Seed the workspace from the legacy example folders in configs/projects/."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from .config import REPO_ROOT
from .store import BUNDLE_FORMAT, BUNDLE_VERSION, WorkspaceStore, clean_author, now_iso

log = logging.getLogger(__name__)

_PROJECT_FILES = frozenset({"project.yaml", "project.yml"})


def examples_root() -> Path:
    return Path(os.environ.get("RESA_WORKSPACE_EXAMPLES_DIR") or REPO_ROOT / "configs" / "projects")


def examples_available() -> bool:
    root = examples_root()
    return root.is_dir() and any(p.is_dir() and any(p.glob("*.yaml")) for p in root.iterdir())


def _label(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return f"{path.parent.name}/{path.name}"


def _project_meta(folder: Path) -> dict[str, Any]:
    path = folder / "project.yaml"
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        log.warning("skipping unreadable %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _engine_config(path: Path) -> dict[str, Any] | None:
    """Fully resolved (base: + file refs) and validated config, or None."""
    from resa.config.loader import load_config

    try:
        cfg = load_config(path)
    except Exception as exc:  # noqa: BLE001 - fragments, broken files: skip with a warning
        log.warning("skipping %s: %s", _label(path), str(exc).splitlines()[0] if str(exc) else exc)
        return None
    data = cfg.model_dump(mode="json", exclude={"config_hash"})
    return {k: v for k, v in data.items() if v is not None}


def _legacy_bundle(folder: Path, author: str) -> dict[str, Any] | None:
    meta = _project_meta(folder)
    primary = meta.get("primary_config")
    files = sorted(p for p in folder.glob("*.yaml") if p.name not in _PROJECT_FILES)
    files.sort(key=lambda p: p.name != primary)  # stable: primary first
    now = now_iso()
    designs = []
    for path in files:
        config = _engine_config(path)
        if config is None:
            continue
        designs.append({
            "name": path.stem,
            "description": str(config.get("description") or ""),
            "status": "concept",
            "is_baseline": path.name == primary,
            "derived_from": None,
            "config": config,
            "versions": [{
                "number": 1,
                "message": f"Imported from {_label(path)}",
                "author": author,
                "created_at": now,
                "kpis": {},
                "config": config,
            }],
        })
    if not designs:
        return None
    return {
        "format": BUNDLE_FORMAT,
        "format_version": BUNDLE_VERSION,
        "exported_at": now,
        "project": {"name": str(meta.get("name") or folder.name), "description": str(meta.get("description") or "")},
        "designs": designs,
    }


def import_examples(store: WorkspaceStore, author: str | None = None) -> list[dict[str, Any]]:
    """Import each legacy project folder once (skipped when its name already exists)."""
    root = examples_root()
    if not root.is_dir():
        return []
    author = clean_author(author)
    existing = {p["name"].casefold() for p in store.list_projects()}
    created = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        name = str(_project_meta(folder).get("name") or folder.name)
        if name.casefold() in existing:
            continue
        bundle = _legacy_bundle(folder, author)
        if bundle is None:
            log.warning("no loadable engine configs in %s", _label(folder))
            continue
        created.append(store.import_bundle(bundle, author))
        existing.add(name.casefold())
    return created


def example_bundles(author: str | None = None) -> list[dict[str, Any]]:
    """Example project bundles without a store (browser-storage mode imports them)."""
    root = examples_root()
    if not root.is_dir():
        return []
    author = clean_author(author)
    bundles = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        bundle = _legacy_bundle(folder, author)
        if bundle is not None:
            bundles.append(bundle)
    return bundles
