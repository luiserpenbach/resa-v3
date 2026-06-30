"""Project folders under configs/projects/ — each holds multiple engine YAML configs."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..settings import PROJECTS_ROOT, REPO_ROOT

_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_RESERVED_CONFIG_NAMES = frozenset({"project.yaml", "project.yml"})
_LEGACY_PRIMARY = "design.yaml"


def _config_stem(name: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_")
    if not stem or stem.lower() == "project":
        raise ValueError("invalid config name")
    return stem


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()
    if not slug or not _SLUG_RE.match(slug):
        raise ValueError(
            "project id must start with a letter or digit and contain only letters, digits, hyphens, underscores"
        )
    return slug


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _read_project_meta(project_dir: Path) -> dict[str, Any]:
    meta_path = project_dir / "project.yaml"
    if meta_path.is_file():
        with meta_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if isinstance(data, dict):
            return data
    return {}


def _primary_config_filename(project_dir: Path, slug: str | None = None) -> str:
    """Return the basename of this project's primary (design) config file."""
    meta = _read_project_meta(project_dir)
    primary = meta.get("primary_config")
    if isinstance(primary, str) and primary.endswith((".yaml", ".yml")):
        if (project_dir / primary).is_file():
            return primary
    if (project_dir / _LEGACY_PRIMARY).is_file():
        return _LEGACY_PRIMARY
    if slug and (project_dir / f"{slug}.yaml").is_file():
        return f"{slug}.yaml"
    return f"{slug or project_dir.name}.yaml"


def _config_entries(project_dir: Path, repo_root: Path) -> list[dict[str, str]]:
    slug = project_dir.name
    primary = _primary_config_filename(project_dir, slug)
    items: list[dict[str, str]] = []
    for path in sorted(project_dir.glob("*.yaml")):
        if path.name in _RESERVED_CONFIG_NAMES:
            continue
        rel = _rel(path, repo_root)
        items.append({
            "path": rel,
            "name": path.stem,
            "filename": path.name,
            "is_primary": path.name == primary,
        })
    return items


_DESIGN_TEMPLATE = """\
engine: "{engine}"
description: "{description}"

propellants:
  name: "N2O/Ethanol"
  oxidizer: NitrousOxide
  fuel: Ethanol
  ox_temp_K: 285
  fuel_temp_K: 293.15

chamber:
  contraction_ratio: 4.0
  l_star_m: 1.0
  contour: rao_bell
  bell_fraction: 0.8
  n_stations: 100

cooling:
  coolant: NitrousOxide
  n_channels: 40
  channel_width_m: 0.0012
  channel_height_m: 0.0015
  rib_width_m: 0.0004
  inner_wall_thickness_m: 0.0006
  wall_material: IN718
  inlet_T_K: 285
  inlet_p_bar: 30
  correlation: gnielinski

combustion:
  backend: rocketcea

operating_point:
  thrust_N: 1000
  pc_bar: 25
  of_ratio: 5.0
  eta_cstar: 0.95
  eta_cf: 0.98
  p_amb_bar: 1.01325
"""

_ANALYZE_TEMPLATE = """\
base: {base_config}
engine: "{engine}"

operating_point: null

geometry:
  throat_diameter_m: 0.03
  eps: 10.0

analyze_point:
  mdot_ox_kg_s: 0.5
  mdot_fuel_kg_s: 0.1
  eta_cstar: 0.95
  eta_cf: 0.98
  p_amb_bar: 1.01325
"""


class ProjectService:
    def __init__(
        self,
        repo_root: Path | None = None,
        projects_root: Path | None = None,
    ) -> None:
        self.repo_root = (repo_root or REPO_ROOT).resolve()
        self.projects_root = (projects_root or PROJECTS_ROOT).resolve()
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, slug: str) -> Path:
        if not _SLUG_RE.match(slug):
            raise ValueError(f"invalid project id: {slug}")
        return self.projects_root / slug

    def list_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        if not self.projects_root.is_dir():
            return projects
        for path in sorted(self.projects_root.iterdir()):
            if not path.is_dir():
                continue
            meta = _read_project_meta(path)
            slug = path.name
            primary = _primary_config_filename(path, slug)
            projects.append({
                "slug": slug,
                "name": meta.get("name") or slug,
                "description": meta.get("description") or "",
                "path": _rel(path, self.repo_root),
                "primary_config": primary,
                "configs": _config_entries(path, self.repo_root),
            })
        return projects

    def get_project(self, slug: str) -> dict[str, Any]:
        project_dir = self._project_dir(slug)
        if not project_dir.is_dir():
            raise FileNotFoundError(f"project not found: {slug}")
        meta = _read_project_meta(project_dir)
        primary = _primary_config_filename(project_dir, slug)
        return {
            "slug": slug,
            "name": meta.get("name") or slug,
            "description": meta.get("description") or "",
            "path": _rel(project_dir, self.repo_root),
            "primary_config": primary,
            "configs": _config_entries(project_dir, self.repo_root),
        }

    def create_project(
        self,
        name: str,
        *,
        slug: str | None = None,
        description: str = "",
        engine: str | None = None,
    ) -> dict[str, Any]:
        project_slug = _slugify(slug or name)
        project_dir = self._project_dir(project_slug)
        if project_dir.exists():
            raise ValueError(f"project already exists: {project_slug}")

        project_dir.mkdir(parents=True)
        engine_name = engine or name.strip().upper().replace(" ", "-")[:32] or project_slug.upper()
        primary_name = f"{project_slug}.yaml"
        meta = {
            "name": name.strip(),
            "description": description.strip(),
            "primary_config": primary_name,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (project_dir / "project.yaml").write_text(
            yaml.safe_dump(meta, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )

        primary_path = project_dir / primary_name
        primary_path.write_text(
            _DESIGN_TEMPLATE.format(engine=engine_name, description=description.strip() or name.strip()),
            encoding="utf-8",
        )

        return {
            "ok": True,
            "slug": project_slug,
            "name": meta["name"],
            "path": _rel(project_dir, self.repo_root),
            "primary_config": primary_name,
            "default_config": _rel(primary_path, self.repo_root),
        }

    def create_config(
        self,
        slug: str,
        config_name: str,
        *,
        mode: str = "design",
        engine: str | None = None,
    ) -> dict[str, Any]:
        project_dir = self._project_dir(slug)
        if not project_dir.is_dir():
            raise FileNotFoundError(f"project not found: {slug}")

        stem = _config_stem(config_name)
        config_path = project_dir / f"{stem}.yaml"
        if config_path.exists():
            raise ValueError(f"config already exists: {stem}.yaml")

        meta = _read_project_meta(project_dir)
        engine_name = engine or meta.get("name") or slug
        primary_name = _primary_config_filename(project_dir, slug)

        if mode == "analyze":
            primary_path = project_dir / primary_name
            if not primary_path.is_file():
                raise ValueError(f"analyze config requires primary config {primary_name} in the project")
            body = _ANALYZE_TEMPLATE.format(
                base_config=primary_name,
                engine=f"{engine_name}-{stem}".upper(),
            )
        else:
            body = _DESIGN_TEMPLATE.format(
                engine=f"{engine_name}-{stem}".upper(),
                description=f"{meta.get('name', slug)} — {stem}",
            )

        config_path.write_text(body, encoding="utf-8")
        return {
            "ok": True,
            "project": slug,
            "config_path": _rel(config_path, self.repo_root),
            "name": stem,
            "mode": mode,
        }

    def list_all_config_paths(self) -> list[dict[str, str]]:
        """Flat list of engine configs under all projects (for legacy /api/config/list)."""
        items: list[dict[str, str]] = []
        for project in self.list_projects():
            for cfg in project["configs"]:
                items.append({
                    "path": cfg["path"],
                    "name": cfg["name"],
                    "filename": cfg["filename"],
                    "project": project["slug"],
                    "project_name": project["name"],
                    "is_primary": str(cfg.get("is_primary", False)).lower(),
                })
        return items
