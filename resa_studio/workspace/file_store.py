"""Git-friendly workspace on disk.

    <root>/<project>/project.yaml                  name, description, created_*, updated_at
    <root>/<project>/designs/<design>.yaml         working-copy engine config only (runnable)
    <root>/<project>/designs/<design>.meta.yaml    name, status, revision, baseline, lineage …
    <root>/<project>/history/<design>/v0001.yaml   {number, message, author, created_at, kpis, config}

Writes are atomic (temp file + os.replace); deletes move into <root>/.trash/.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .store import (
    DEFAULT_STATUS,
    ID_RE,
    Conflict,
    NotFound,
    WorkspaceStore,
    as_iso,
    check_config,
    check_id,
    check_kpis,
    check_status,
    clean_author,
    clean_description,
    clean_message,
    clean_name,
    design_summary,
    now_iso,
    slugify,
    sort_designs,
    sort_projects,
    unique_id,
    version_full,
    version_summary,
)

_VERSION_FILE_RE = re.compile(r"^v(\d+)\.yaml$")
_META_SUFFIX = ".meta.yaml"
_META_KEYS = (
    "name", "description", "status", "revision", "created_at", "created_by",
    "updated_at", "updated_by", "derived_from", "is_baseline",
)


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write_yaml(path: Path, data: Any) -> None:
    """Atomic write: temp file in the same directory, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _claim(path: Path) -> bool:
    """Create *path* exclusively (cross-process id reservation)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
    except FileExistsError:
        return False
    return True


def _trash_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


class FileStore(WorkspaceStore):
    kind = "files"

    def __init__(self, root: Path | str, label: str | None = None) -> None:
        self.root = Path(root)
        self._label = label
        self._lock = threading.RLock()

    @property
    def location(self) -> str:
        return self._label or str(self.root)

    # ── paths ────────────────────────────────────────────────────────────────

    def _project_dir(self, project_id: str) -> Path:
        return self.root / check_id(project_id, "project id")

    def _designs_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "designs"

    def _config_path(self, project_id: str, design_id: str) -> Path:
        return self._designs_dir(project_id) / f"{check_id(design_id, 'design id')}.yaml"

    def _meta_path(self, project_id: str, design_id: str) -> Path:
        return self._designs_dir(project_id) / f"{check_id(design_id, 'design id')}{_META_SUFFIX}"

    def _history_dir(self, project_id: str, design_id: str) -> Path:
        return self._project_dir(project_id) / "history" / check_id(design_id, "design id")

    def _version_path(self, project_id: str, design_id: str, number: int) -> Path:
        return self._history_dir(project_id, design_id) / f"v{number:04d}.yaml"

    def _trash_dir(self, name: str) -> Path:
        trash = self.root / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        return trash / f"{_trash_stamp()}-{name}"

    # ── raw records ──────────────────────────────────────────────────────────

    def _project_meta(self, project_id: str) -> dict[str, Any]:
        path = self._project_dir(project_id) / "project.yaml"
        if not path.is_file():
            raise NotFound(f"project not found: {project_id}")
        raw = _read_yaml(path)
        raw = raw if isinstance(raw, dict) else {}
        return {
            "id": project_id,
            "name": str(raw.get("name") or project_id),
            "description": str(raw.get("description") or ""),
            "created_at": as_iso(raw.get("created_at")),
            "created_by": str(raw.get("created_by") or ""),
            "updated_at": as_iso(raw.get("updated_at")),
        }

    def _write_project_meta(self, meta: dict[str, Any]) -> None:
        data = {k: meta[k] for k in ("name", "description", "created_at", "created_by", "updated_at")}
        _write_yaml(self._project_dir(meta["id"]) / "project.yaml", data)

    def _design_ids(self, project_id: str) -> list[str]:
        designs_dir = self._designs_dir(project_id)
        if not designs_dir.is_dir():
            return []
        ids = []
        for path in designs_dir.glob("*.yaml"):
            if path.name.endswith(_META_SUFFIX):
                continue
            if ID_RE.match(path.stem):
                ids.append(path.stem)
        return sorted(ids)

    def _design_meta(self, project_id: str, design_id: str) -> dict[str, Any]:
        """Metadata; a design YAML added by hand (no .meta.yaml) gets defaults."""
        config_path = self._config_path(project_id, design_id)
        if not config_path.is_file():
            self._project_meta(project_id)
            raise NotFound(f"design not found: {project_id}/{design_id}")
        meta_path = self._meta_path(project_id, design_id)
        raw = _read_yaml(meta_path) if meta_path.is_file() else None
        raw = raw if isinstance(raw, dict) else {}
        mtime = datetime.fromtimestamp(config_path.stat().st_mtime, tz=timezone.utc)
        return {
            "id": design_id,
            "name": str(raw.get("name") or design_id),
            "description": str(raw.get("description") or ""),
            "status": raw.get("status") or DEFAULT_STATUS,
            "revision": int(raw.get("revision") or 1),
            "created_at": as_iso(raw.get("created_at") or mtime),
            "created_by": str(raw.get("created_by") or ""),
            "updated_at": as_iso(raw.get("updated_at") or mtime),
            "updated_by": str(raw.get("updated_by") or ""),
            "derived_from": raw.get("derived_from"),
            "is_baseline": bool(raw.get("is_baseline")),
        }

    def _write_design_meta(self, project_id: str, meta: dict[str, Any]) -> None:
        _write_yaml(self._meta_path(project_id, meta["id"]), {k: meta[k] for k in _META_KEYS})

    def _read_config(self, project_id: str, design_id: str) -> dict[str, Any]:
        raw = _read_yaml(self._config_path(project_id, design_id))
        return raw if isinstance(raw, dict) else {}

    def _version_numbers(self, project_id: str, design_id: str) -> list[int]:
        history = self._history_dir(project_id, design_id)
        if not history.is_dir():
            return []
        numbers = []
        for path in history.iterdir():
            m = _VERSION_FILE_RE.match(path.name)
            if m:
                numbers.append(int(m.group(1)))
        return sorted(numbers)

    def _read_version(self, project_id: str, design_id: str, number: int) -> dict[str, Any]:
        path = self._version_path(project_id, design_id, number)
        if not path.is_file():
            raise NotFound(f"version not found: {project_id}/{design_id} v{number}")
        raw = _read_yaml(path)
        raw = raw if isinstance(raw, dict) else {}
        config = raw.get("config")
        return {
            "number": number,
            "message": str(raw.get("message") or ""),
            "author": str(raw.get("author") or ""),
            "created_at": as_iso(raw.get("created_at")),
            "kpis": raw.get("kpis") if isinstance(raw.get("kpis"), dict) else {},
            "config": config if isinstance(config, dict) else {},
        }

    def _head(self, project_id: str, design_id: str) -> dict[str, Any] | None:
        numbers = self._version_numbers(project_id, design_id)
        return self._read_version(project_id, design_id, numbers[-1]) if numbers else None

    def _summary(self, project_id: str, design_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        meta = self._design_meta(project_id, design_id)
        config = self._read_config(project_id, design_id)
        return design_summary(project_id, meta, config, self._head(project_id, design_id)), config

    def _write_version(self, project_id: str, design_id: str, version: dict[str, Any]) -> None:
        _write_yaml(self._version_path(project_id, design_id, version["number"]), version_full(version))

    # ── projects ─────────────────────────────────────────────────────────────

    def _project(self, project_id: str) -> dict[str, Any]:
        meta = self._project_meta(project_id)
        # Activity inside the project counts as an update without rewriting
        # project.yaml on every autosave (keeps git diffs quiet).
        designs = [self._design_meta(project_id, did) for did in self._design_ids(project_id)]
        updated = max([meta["updated_at"], *(d["updated_at"] for d in designs)])
        return {**meta, "updated_at": updated, "design_count": len(designs)}

    def list_projects(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        projects = []
        for path in self.root.iterdir():
            if path.is_dir() and ID_RE.match(path.name) and (path / "project.yaml").is_file():
                projects.append(self._project(path.name))
        return sort_projects(projects)

    def get_project(self, project_id: str) -> dict[str, Any]:
        return self._project(project_id)

    def _new_project_dir(self, name: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        base = slugify(name)
        taken: set[str] = set()
        while True:
            project_id = unique_id(base, taken)
            try:
                (self.root / project_id).mkdir()
                return project_id
            except FileExistsError:
                taken.add(project_id)

    def create_project(self, name: str, description: str = "", author: str | None = None) -> dict[str, Any]:
        name, description, author = clean_name(name), clean_description(description), clean_author(author)
        with self._lock:
            project_id = self._new_project_dir(name)
            now = now_iso()
            self._write_project_meta({
                "id": project_id, "name": name, "description": description,
                "created_at": now, "created_by": author, "updated_at": now,
            })
            (self.root / project_id / "designs").mkdir(exist_ok=True)
            return self._project(project_id)

    def update_project(
        self, project_id: str, *, name: str | None = None, description: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            meta = self._project_meta(project_id)
            if name is not None:
                meta["name"] = clean_name(name)
            if description is not None:
                meta["description"] = clean_description(description)
            meta["updated_at"] = now_iso()
            self._write_project_meta(meta)
            return self._project(project_id)

    def delete_project(self, project_id: str) -> None:
        with self._lock:
            self._project_meta(project_id)
            shutil.move(str(self._project_dir(project_id)), str(self._trash_dir(project_id)))

    def _touch_project(self, project_id: str) -> None:
        meta = self._project_meta(project_id)
        meta["updated_at"] = now_iso()
        self._write_project_meta(meta)

    # ── designs ──────────────────────────────────────────────────────────────

    def list_designs(self, project_id: str) -> list[dict[str, Any]]:
        self._project_meta(project_id)
        return sort_designs([self._summary(project_id, did)[0] for did in self._design_ids(project_id)])

    def get_design(self, project_id: str, design_id: str) -> dict[str, Any]:
        summary, config = self._summary(project_id, design_id)
        return {**summary, "config": config}

    def _new_design_id(self, project_id: str, name: str) -> str:
        taken = set(self._design_ids(project_id))
        base = slugify(name)
        while True:
            design_id = unique_id(base, taken)
            if not self._meta_path(project_id, design_id).exists() and _claim(
                self._config_path(project_id, design_id)
            ):
                return design_id
            taken.add(design_id)

    def _insert_design(
        self,
        project_id: str,
        name: str,
        description: str,
        config: dict[str, Any],
        author: str,
        derived_from: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with self._lock:
            self._project_meta(project_id)
            design_id = self._new_design_id(project_id, name)
            now = now_iso()
            self._write_design_meta(project_id, {
                "id": design_id, "name": name, "description": description, "status": DEFAULT_STATUS,
                "revision": 1, "created_at": now, "created_by": author, "updated_at": now,
                "updated_by": author, "derived_from": derived_from, "is_baseline": False,
            })
            _write_yaml(self._config_path(project_id, design_id), config)
            return self.get_design(project_id, design_id)

    def update_design(
        self,
        project_id: str,
        design_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        is_baseline: bool | None = None,
        author: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            meta = self._design_meta(project_id, design_id)
            if name is not None:
                meta["name"] = clean_name(name)
            if description is not None:
                meta["description"] = clean_description(description)
            if status is not None:
                meta["status"] = check_status(status)
            if is_baseline is not None:
                if is_baseline:
                    for other_id in self._design_ids(project_id):
                        if other_id == design_id:
                            continue
                        other = self._design_meta(project_id, other_id)
                        if other["is_baseline"]:
                            other["is_baseline"] = False
                            self._write_design_meta(project_id, other)
                meta["is_baseline"] = bool(is_baseline)
            meta["updated_at"] = now_iso()
            meta["updated_by"] = clean_author(author)
            self._write_design_meta(project_id, meta)
            return self._summary(project_id, design_id)[0]

    def delete_design(self, project_id: str, design_id: str) -> None:
        with self._lock:
            self._design_meta(project_id, design_id)
            dest = self._trash_dir(f"{project_id}.{design_id}")
            dest.mkdir()
            for src, name in (
                (self._config_path(project_id, design_id), f"{design_id}.yaml"),
                (self._meta_path(project_id, design_id), f"{design_id}{_META_SUFFIX}"),
                (self._history_dir(project_id, design_id), "history"),
            ):
                if src.exists():
                    shutil.move(str(src), str(dest / name))
            self._touch_project(project_id)

    def save_draft(
        self, project_id: str, design_id: str, config: dict[str, Any], revision: int, author: str | None = None,
    ) -> dict[str, Any]:
        config = check_config(config)
        with self._lock:
            meta = self._design_meta(project_id, design_id)
            if revision != meta["revision"]:
                raise Conflict(
                    f"design {design_id} was changed by {meta['updated_by'] or 'someone else'} "
                    f"(revision {meta['revision']}, you have {revision})",
                    current_revision=meta["revision"],
                )
            _write_yaml(self._config_path(project_id, design_id), config)
            meta.update(revision=meta["revision"] + 1, updated_at=now_iso(), updated_by=clean_author(author))
            self._write_design_meta(project_id, meta)
            head = self._head(project_id, design_id)
            return {
                "revision": meta["revision"],
                "updated_at": meta["updated_at"],
                "has_unsaved_changes": head is None or head["config"] != config,
            }

    # ── versions ─────────────────────────────────────────────────────────────

    def create_version(
        self,
        project_id: str,
        design_id: str,
        message: str,
        author: str | None = None,
        kpis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message, author, kpis = clean_message(message), clean_author(author), check_kpis(kpis)
        with self._lock:
            meta = self._design_meta(project_id, design_id)
            config = self._read_config(project_id, design_id)
            numbers = self._version_numbers(project_id, design_id)
            number = (numbers[-1] if numbers else 0) + 1
            while not _claim(self._version_path(project_id, design_id, number)):
                number += 1
            version = {
                "number": number, "message": message, "author": author,
                "created_at": now_iso(), "kpis": kpis, "config": config,
            }
            self._write_version(project_id, design_id, version)
            meta.update(updated_at=version["created_at"], updated_by=author)
            self._write_design_meta(project_id, meta)
            return version_summary(version)

    def list_versions(self, project_id: str, design_id: str) -> list[dict[str, Any]]:
        self._design_meta(project_id, design_id)
        return [
            version_summary(self._read_version(project_id, design_id, n))
            for n in reversed(self._version_numbers(project_id, design_id))
        ]

    def get_version(self, project_id: str, design_id: str, number: int) -> dict[str, Any]:
        self._design_meta(project_id, design_id)
        return version_full(self._read_version(project_id, design_id, number))

    def restore_version(
        self, project_id: str, design_id: str, number: int, author: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            meta = self._design_meta(project_id, design_id)
            version = self._read_version(project_id, design_id, number)
            _write_yaml(self._config_path(project_id, design_id), version["config"])
            meta.update(revision=meta["revision"] + 1, updated_at=now_iso(), updated_by=clean_author(author))
            self._write_design_meta(project_id, meta)
            return self.get_design(project_id, design_id)

    # ── bundles ──────────────────────────────────────────────────────────────

    def _insert_bundle(self, data: dict[str, Any], author: str) -> dict[str, Any]:
        with self._lock:
            project_id = self._new_project_dir(data["name"])
            now = now_iso()
            self._write_project_meta({
                "id": project_id, "name": data["name"], "description": data["description"],
                "created_at": now, "created_by": author, "updated_at": now,
            })
            (self.root / project_id / "designs").mkdir(exist_ok=True)
            for design in data["designs"]:
                design_id = design["id"]
                self._write_design_meta(project_id, {
                    "id": design_id, "name": design["name"], "description": design["description"],
                    "status": design["status"], "revision": 1, "created_at": now, "created_by": author,
                    "updated_at": now, "updated_by": author, "derived_from": design["derived_from"],
                    "is_baseline": design["is_baseline"],
                })
                for version in design["versions"]:
                    self._write_version(project_id, design_id, version)
                _write_yaml(self._config_path(project_id, design_id), design["config"])
            return self._project(project_id)

