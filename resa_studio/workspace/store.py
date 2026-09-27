"""Workspace store interface: projects → engine designs → version history.

A design is a working copy (autosaved draft, plain engine-config dict) plus an
append-only list of versions (checkpoints with message, author and a KPI
snapshot). Configs are opaque to the store — drafts may be invalid mid-edit.
"""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SLUG_MAX = 48
STATUSES = ("concept", "preliminary", "detailed", "frozen")
DEFAULT_STATUS = "concept"
DEFAULT_AUTHOR = "anonymous"
MAX_NAME = 120
MAX_DESCRIPTION = 4000
MAX_MESSAGE = 500
MAX_AUTHOR = 120
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_KPIS_BYTES = 256 * 1024
BUNDLE_FORMAT = "resa-project"
BUNDLE_VERSION = 1


class WorkspaceError(Exception):
    """Base class for store errors that map onto HTTP status codes."""


class NotFound(WorkspaceError):
    pass


class Invalid(WorkspaceError):
    pass


class TooLarge(WorkspaceError):
    pass


class Conflict(WorkspaceError):
    def __init__(self, message: str, current_revision: int | None = None) -> None:
        super().__init__(message)
        self.current_revision = current_revision


# ── helpers shared by both stores ────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def as_iso(value: Any) -> str:
    """Coerce a timestamp read back from YAML (hand-edited files) to an ISO string."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return str(value) if value is not None else ""


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug[:SLUG_MAX].strip("-") or "untitled"


def unique_id(base: str, taken: set[str] | frozenset[str]) -> str:
    """*base*, or *base*-2, -3 … (kept within SLUG_MAX) — the first not in *taken*."""
    if base not in taken:
        return base
    n = 2
    while True:
        suffix = f"-{n}"
        candidate = base[: SLUG_MAX - len(suffix)].rstrip("-") + suffix
        if candidate not in taken:
            return candidate
        n += 1


def check_id(value: Any, kind: str = "id") -> str:
    if not isinstance(value, str) or not ID_RE.match(value):
        raise Invalid(f"invalid {kind}: {value!r}")
    return value


def clean_name(value: Any, field: str = "name") -> str:
    name = value.strip() if isinstance(value, str) else ""
    if not name or len(name) > MAX_NAME:
        raise Invalid(f"{field} must be 1..{MAX_NAME} characters")
    return name


def clean_description(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MAX_DESCRIPTION:
        raise Invalid(f"description must be a string of at most {MAX_DESCRIPTION} characters")
    return value.strip()


def clean_author(value: Any) -> str:
    author = value.strip() if isinstance(value, str) else ""
    return author[:MAX_AUTHOR] or DEFAULT_AUTHOR


def clean_message(value: Any) -> str:
    message = value.strip() if isinstance(value, str) else ""
    if not message or len(message) > MAX_MESSAGE:
        raise Invalid(f"message must be 1..{MAX_MESSAGE} characters")
    return message


def check_status(value: Any) -> str:
    if value not in STATUSES:
        raise Invalid(f"status must be one of {', '.join(STATUSES)}")
    return value


def _plain_json(value: Any, what: str, limit: int) -> Any:
    """Deep copy through JSON: rejects non-JSON values, enforces the size limit."""
    try:
        blob = json.dumps(value, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise Invalid(f"{what} is not plain JSON: {exc}") from exc
    if len(blob.encode()) > limit:
        raise TooLarge(f"{what} exceeds {limit // 1024} KiB")
    return json.loads(blob)


def check_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise Invalid("config must be an object")
    return _plain_json(config, "config", MAX_CONFIG_BYTES)


def check_kpis(kpis: Any) -> dict[str, Any]:
    if kpis is None:
        return {}
    if not isinstance(kpis, dict):
        raise Invalid("kpis must be an object")
    return _plain_json(kpis, "kpis", MAX_KPIS_BYTES)


def to_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def origin_dict(value: Any) -> dict[str, Any] | None:
    """Normalize a stored ``derived_from`` record."""
    if not isinstance(value, dict) or not isinstance(value.get("design_id"), str):
        return None
    version = value.get("version")
    return {
        "design_id": value["design_id"],
        "design_name": str(value.get("design_name") or value["design_id"]),
        "version": version if isinstance(version, int) and not isinstance(version, bool) else None,
    }


def design_summary(
    project_id: str,
    meta: dict[str, Any],
    config: dict[str, Any],
    head: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a DesignSummary from design metadata, working copy and latest version."""
    return {
        "id": meta["id"],
        "project_id": project_id,
        "name": meta["name"],
        "description": meta.get("description") or "",
        "status": meta.get("status") or DEFAULT_STATUS,
        "revision": int(meta.get("revision") or 1),
        "head_version": head["number"] if head else None,
        "has_unsaved_changes": head is None or head["config"] != config,
        "created_at": meta.get("created_at") or "",
        "created_by": meta.get("created_by") or "",
        "updated_at": meta.get("updated_at") or "",
        "updated_by": meta.get("updated_by") or "",
        "derived_from": origin_dict(meta.get("derived_from")),
        "is_baseline": bool(meta.get("is_baseline")),
        "kpis": copy.deepcopy(head["kpis"]) if head else {},
    }


def version_summary(version: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": version["number"],
        "message": version["message"],
        "author": version["author"],
        "created_at": version["created_at"],
        "kpis": copy.deepcopy(version.get("kpis") or {}),
    }


def version_full(version: dict[str, Any]) -> dict[str, Any]:
    return {**version_summary(version), "config": copy.deepcopy(version["config"])}


def sort_designs(designs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(designs, key=lambda d: (not d["is_baseline"], d["name"].casefold(), d["id"]))


def sort_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(projects, key=lambda p: (p["updated_at"], p["id"]), reverse=True)


def validate_bundle(bundle: Any) -> dict[str, Any]:
    """Check an exported project bundle; return a normalized copy for import."""
    if not isinstance(bundle, dict):
        raise Invalid("bundle must be an object")
    if bundle.get("format") != BUNDLE_FORMAT:
        raise Invalid(f"bundle format must be {BUNDLE_FORMAT!r}")
    if bundle.get("format_version") != BUNDLE_VERSION:
        raise Invalid(f"unsupported bundle format_version: {bundle.get('format_version')!r}")
    project = bundle.get("project")
    if not isinstance(project, dict):
        raise Invalid("bundle.project must be an object")
    raw_designs = bundle.get("designs", [])
    if not isinstance(raw_designs, list):
        raise Invalid("bundle.designs must be a list")

    designs: list[dict[str, Any]] = []
    taken: set[str] = set()
    id_map: dict[str, str] = {}
    baseline_seen = False
    for i, raw in enumerate(raw_designs):
        if not isinstance(raw, dict):
            raise Invalid(f"bundle.designs[{i}] must be an object")
        name = clean_name(raw.get("name"), f"designs[{i}].name")
        old_id = raw.get("id")
        base = old_id if isinstance(old_id, str) and ID_RE.match(old_id) else slugify(name)
        design_id = unique_id(base, taken)
        taken.add(design_id)
        if isinstance(old_id, str):
            id_map[old_id] = design_id

        versions: list[dict[str, Any]] = []
        raw_versions = raw.get("versions", [])
        if not isinstance(raw_versions, list):
            raise Invalid(f"designs[{i}].versions must be a list")
        for j, rv in enumerate(raw_versions):
            if not isinstance(rv, dict):
                raise Invalid(f"designs[{i}].versions[{j}] must be an object")
            number = rv.get("number")
            if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                raise Invalid(f"designs[{i}].versions[{j}].number must be a positive integer")
            versions.append({
                "number": number,
                "message": clean_message(rv.get("message")),
                "author": clean_author(rv.get("author")),
                "created_at": as_iso(rv.get("created_at")) or now_iso(),
                "kpis": check_kpis(rv.get("kpis")),
                "config": check_config(rv.get("config")),
            })
        versions.sort(key=lambda v: v["number"])
        if len({v["number"] for v in versions}) != len(versions):
            raise Invalid(f"designs[{i}] has duplicate version numbers")

        is_baseline = bool(raw.get("is_baseline")) and not baseline_seen
        baseline_seen = baseline_seen or is_baseline
        designs.append({
            "id": design_id,
            "name": name,
            "description": clean_description(raw.get("description")),
            "status": check_status(raw.get("status") or DEFAULT_STATUS),
            "is_baseline": is_baseline,
            "derived_from": origin_dict(raw.get("derived_from")),
            "config": check_config(raw.get("config")),
            "versions": versions,
        })

    for design in designs:
        origin = design["derived_from"]
        if origin and origin["design_id"] in id_map:
            origin["design_id"] = id_map[origin["design_id"]]
    return {
        "name": clean_name(project.get("name"), "project.name"),
        "description": clean_description(project.get("description")),
        "designs": designs,
    }


# ── interface ────────────────────────────────────────────────────────────────

class WorkspaceStore(ABC):
    """Abstract persistence for projects, designs and versions.

    All returned dicts are fresh copies; all timestamps are ISO-8601 UTC ("Z").
    Methods raise NotFound / Conflict / Invalid / TooLarge.
    """

    kind: str = ""  # "files" | "database"
    writable: bool = True

    @property
    @abstractmethod
    def location(self) -> str:
        """Human-readable label of where data lives (no credentials)."""

    # projects
    @abstractmethod
    def list_projects(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_project(self, project_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def create_project(self, name: str, description: str = "", author: str | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def update_project(
        self, project_id: str, *, name: str | None = None, description: str | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def delete_project(self, project_id: str) -> None: ...

    # designs
    @abstractmethod
    def list_designs(self, project_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_design(self, project_id: str, design_id: str) -> dict[str, Any]: ...

    @abstractmethod
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
    ) -> dict[str, Any]: ...

    @abstractmethod
    def delete_design(self, project_id: str, design_id: str) -> None: ...

    @abstractmethod
    def save_draft(
        self, project_id: str, design_id: str, config: dict[str, Any], revision: int, author: str | None = None,
    ) -> dict[str, Any]:
        """Overwrite the working copy; raise Conflict unless *revision* is current."""

    # versions
    @abstractmethod
    def create_version(
        self,
        project_id: str,
        design_id: str,
        message: str,
        author: str | None = None,
        kpis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Snapshot the current working copy as the next version number."""

    @abstractmethod
    def list_versions(self, project_id: str, design_id: str) -> list[dict[str, Any]]:
        """Version summaries, newest first."""

    @abstractmethod
    def get_version(self, project_id: str, design_id: str, number: int) -> dict[str, Any]: ...

    @abstractmethod
    def restore_version(
        self, project_id: str, design_id: str, number: int, author: str | None = None,
    ) -> dict[str, Any]:
        """Copy a version's config into the working copy (new revision, no new version)."""

    # primitives used by the shared implementations below
    @abstractmethod
    def _insert_design(
        self,
        project_id: str,
        name: str,
        description: str,
        config: dict[str, Any],
        author: str,
        derived_from: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Create a design with a unique id derived from *name*; return the full Design."""

    @abstractmethod
    def _insert_bundle(self, data: dict[str, Any], author: str) -> dict[str, Any]:
        """Write a validated bundle (see validate_bundle) as a new project; return it."""

    # shared implementations
    def create_design(
        self,
        project_id: str,
        name: str,
        *,
        description: str = "",
        config: dict[str, Any] | None = None,
        author: str | None = None,
        derived_from: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a design; with *derived_from* and no *config*, branch the source's config."""
        check_id(project_id, "project id")
        name = clean_name(name)
        description = clean_description(description)
        origin = None
        if derived_from:
            source = self.get_design(project_id, check_id(derived_from.get("design_id"), "design id"))
            version = derived_from.get("version")
            if version is not None:
                source_config = self.get_version(project_id, source["id"], int(version))["config"]
            else:
                source_config = source["config"]
            origin = {"design_id": source["id"], "design_name": source["name"], "version": version}
            if config is None:
                config = source_config
        if config is None:
            raise Invalid("config is required unless derived_from is given")
        return self._insert_design(
            project_id, name, description, check_config(config), clean_author(author), origin,
        )

    def export_project(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        designs = []
        for summary in self.list_designs(project_id):
            design = self.get_design(project_id, summary["id"])
            versions = [
                self.get_version(project_id, design["id"], v["number"])
                for v in reversed(self.list_versions(project_id, design["id"]))
            ]
            designs.append({
                "id": design["id"],
                "name": design["name"],
                "description": design["description"],
                "status": design["status"],
                "is_baseline": design["is_baseline"],
                "derived_from": design["derived_from"],
                "config": design["config"],
                "versions": versions,
            })
        return {
            "format": BUNDLE_FORMAT,
            "format_version": BUNDLE_VERSION,
            "exported_at": now_iso(),
            "project": {
                "name": project["name"],
                "description": project["description"],
                "created_at": project["created_at"],
                "created_by": project["created_by"],
            },
            "designs": designs,
        }

    def import_bundle(self, bundle: dict[str, Any], author: str | None = None) -> dict[str, Any]:
        """Create a new project from an export bundle (project id renamed on collision)."""
        return self._insert_bundle(validate_bundle(bundle), clean_author(author))
