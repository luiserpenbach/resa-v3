"""Config load/validate — wraps resa.config without touching models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from resa.config.loader import (
    _REF_KEYS,
    load_config,
    load_inherited_dict,
    load_resolved_dict,
    read_raw_config,
    resolve_file_ref,
)
from resa.config.schema import EngineConfig

from ..settings import CONFIGS_ROOT, OUT_ROOT, PROJECTS_ROOT, REPO_ROOT, rel_to


def _config_hash(data: dict[str, Any]) -> str:
    blob = json.dumps(data, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def _deep_equal(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _diff_overlay(base: Any, updated: Any) -> dict[str, Any] | None:
    """Return nested dict of values in *updated* that differ from *base*."""
    if not isinstance(updated, dict):
        return None
    if not isinstance(base, dict):
        base = {}
    out: dict[str, Any] = {}
    for key, val in updated.items():
        if key == "config_hash":
            continue
        inherited = base.get(key)
        if isinstance(val, dict) and isinstance(inherited, dict):
            sub = _diff_overlay(inherited, val)
            if sub:
                out[key] = sub
        elif not _deep_equal(val, inherited):
            out[key] = val
    return out or None


def _preserve_file_refs(
    path: Path,
    payload: dict[str, Any],
    clean: dict[str, Any],
    raw_on_disk: dict[str, Any],
) -> None:
    """Restore ``key: fragment.yaml`` strings when resolved content is unchanged."""
    for key in _REF_KEYS:
        raw_val = raw_on_disk.get(key)
        if not isinstance(raw_val, str) or not raw_val.endswith((".yaml", ".yml")):
            continue
        ref_resolved = resolve_file_ref(raw_val, path.parent)
        if _deep_equal(clean.get(key), ref_resolved):
            payload[key] = raw_val
        elif key in payload and _deep_equal(payload[key], ref_resolved):
            payload[key] = raw_val


def _strip_ui_null_mode_blocks(payload: dict[str, Any], raw_on_disk: dict[str, Any]) -> None:
    """Drop null mode blocks the editor injects but were not on disk originally."""
    for key in ("analyze_point", "geometry", "operating_point"):
        if payload.get(key) is None and key not in raw_on_disk:
            payload.pop(key, None)


def _build_save_payload(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Build YAML body: full config, or thin ``base:`` overlay when applicable."""
    clean = {k: v for k, v in data.items() if k != "config_hash"}
    raw_on_disk = read_raw_config(path)
    base_ref = raw_on_disk.get("base")
    if not base_ref:
        payload = dict(clean)
        _preserve_file_refs(path, payload, clean, raw_on_disk)
        _strip_ui_null_mode_blocks(payload, raw_on_disk)
        return payload

    inherited = load_inherited_dict(path)
    overlay = _diff_overlay(inherited, clean) or {}

    # Preserve the relative base path, and explicit nulls (e.g.
    # operating_point: null) only while the edited config still has no value
    # there — a user edit to a nulled key must win over the null on disk.
    overlay["base"] = base_ref
    for key, val in raw_on_disk.items():
        if val is None and clean.get(key) is None:
            overlay[key] = None

    # Drop inherited-equal branches (except base and explicit nulls).
    for key in list(overlay):
        if key in ("base",) or overlay[key] is None:
            continue
        if key not in clean:
            del overlay[key]
            continue
        if _deep_equal(clean.get(key), inherited.get(key)):
            del overlay[key]

    # Restore fragment refs after the drop above, so a ref pin whose content
    # happens to equal the inherited value is kept rather than deleted.
    _preserve_file_refs(path, overlay, clean, raw_on_disk)

    if len(overlay) == 1 and "base" in overlay:
        # Only base left — keep any keys that were in the original thin file.
        for key, val in raw_on_disk.items():
            if key != "base" and key not in overlay:
                overlay[key] = clean.get(key, val)

    _strip_ui_null_mode_blocks(overlay, raw_on_disk)
    return overlay


class ConfigService:
    def __init__(
        self,
        repo_root: Path | None = None,
        configs_root: Path | None = None,
        projects_root: Path | None = None,
        out_root: Path | None = None,
    ) -> None:
        self.repo_root = (repo_root or REPO_ROOT).resolve()
        self.configs_root = (configs_root or CONFIGS_ROOT).resolve()
        self.projects_root = (projects_root or PROJECTS_ROOT).resolve()
        self.out_root = (out_root or OUT_ROOT).resolve()

    def _resolve_path(self, config_path: str | Path) -> Path:
        path = Path(config_path)
        if not path.is_absolute():
            path = (self.repo_root / path).resolve()
        else:
            path = path.resolve()
        # Confine to the known roots (proper ancestor check, not a string
        # prefix that a sibling directory could satisfy). configs/projects/out
        # roots may be relocated outside the repo via RESA_*_ROOT.
        allowed = (self.repo_root, self.configs_root, self.projects_root,
                   self.out_root)
        if not any(path.is_relative_to(root) for root in allowed):
            raise ValueError(f"config path must stay under project root: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"config not found: {path}")
        return path

    def _rel(self, path: Path) -> str:
        return rel_to(path, self.repo_root)

    def _path_info(self, path: Path) -> dict[str, Any]:
        rel = self._rel(path)
        # Run snapshots (out/**/config_resolved.yaml) are read-only: save_config
        # only accepts project configs, so advertising them as writable
        # produced an Edit flow whose Save always failed.
        writable = path.is_relative_to(self.projects_root)
        return {
            "writable": writable,
            "save_path": rel,
            "is_override": False,
        }

    def load_path(self, config_path: str | Path) -> tuple[EngineConfig, Path]:
        path = self._resolve_path(config_path)
        return load_config(path), path

    def validate_dict(self, data: dict[str, Any]) -> EngineConfig:
        cfg = EngineConfig.model_validate(data)
        return cfg.model_copy(update={"config_hash": _config_hash(data)})

    def validate_path(self, config_path: str | Path) -> EngineConfig:
        cfg, _ = self.load_path(config_path)
        return cfg

    def resolve_path(self, config_path: str | Path) -> dict[str, Any]:
        """Return fully resolved config dict for UI editing."""
        path = self._resolve_path(config_path)
        data = load_resolved_dict(path)
        cfg = load_config(path)
        info = self._path_info(path)
        return {
            "config_path": self._rel(path),
            "config": data,
            "engine": cfg.engine,
            "mode": cfg.mode,
            "config_hash": cfg.config_hash,
            **info,
        }

    def save_config(self, config_path: str, data: dict[str, Any]) -> dict[str, Any]:
        """Validate and write config to the file being edited."""
        source = self._resolve_path(config_path)
        rel = self._rel(source)
        if not source.is_relative_to(self.projects_root):
            raise ValueError(f"config must live under the projects root: {rel}")
        info = self._path_info(source)
        if not info["writable"]:
            raise ValueError(f"config path is not writable: {self._rel(source)}")
        cfg = self.validate_dict(data)
        payload = _build_save_payload(source, data)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "config_path": self._rel(source),
            "source_path": self._rel(source),
            "engine": cfg.engine,
            "mode": cfg.mode,
            "config_hash": cfg.config_hash,
            "created_override": False,
        }

    def path_info(self, config_path: str | Path) -> dict[str, Any]:
        path = Path(config_path)
        if not path.is_absolute():
            path = (self.repo_root / path).resolve()
        else:
            path = path.resolve()
        return self._path_info(path)

    def schema(self) -> dict[str, Any]:
        return EngineConfig.model_json_schema()

    def list_configs(self) -> list[dict[str, str]]:
        """Discover engine YAML configs under configs/projects/."""
        from .project_service import ProjectService

        return ProjectService(self.repo_root, PROJECTS_ROOT).list_all_config_paths()

    @staticmethod
    def format_validation_error(exc: ValidationError) -> list[dict[str, Any]]:
        return [
            {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
            for err in exc.errors()
        ]
