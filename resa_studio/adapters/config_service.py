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

from ..settings import CONFIGS_ROOT, PROJECTS_ROOT, REPO_ROOT


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


def _build_save_payload(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Build YAML body: full config, or thin ``base:`` overlay when applicable."""
    clean = {k: v for k, v in data.items() if k != "config_hash"}
    raw_on_disk = read_raw_config(path)
    base_ref = raw_on_disk.get("base")
    if not base_ref:
        return clean

    inherited = load_inherited_dict(path)
    overlay = _diff_overlay(inherited, clean) or {}

    # Preserve relative base path and explicit nulls (e.g. operating_point: null).
    overlay["base"] = base_ref
    for key, val in raw_on_disk.items():
        if val is None:
            overlay[key] = None

    # Keep file-reference strings when the resolved content is unchanged.
    for key in _REF_KEYS:
        raw_val = raw_on_disk.get(key)
        if not isinstance(raw_val, str) or not raw_val.endswith((".yaml", ".yml")):
            continue
        ref_resolved = resolve_file_ref(raw_val, path.parent)
        if _deep_equal(clean.get(key), ref_resolved):
            overlay[key] = raw_val
        elif key in overlay and _deep_equal(overlay[key], ref_resolved):
            overlay[key] = raw_val

    # Drop inherited-equal branches (except base and explicit nulls).
    for key in list(overlay):
        if key in ("base",) or overlay[key] is None:
            continue
        if key not in clean:
            del overlay[key]
            continue
        if _deep_equal(clean.get(key), inherited.get(key)):
            del overlay[key]

    if len(overlay) == 1 and "base" in overlay:
        # Only base left — keep any keys that were in the original thin file.
        for key, val in raw_on_disk.items():
            if key != "base" and key not in overlay:
                overlay[key] = clean.get(key, val)

    return overlay


class ConfigService:
    def __init__(
        self,
        repo_root: Path | None = None,
        configs_root: Path | None = None,
    ) -> None:
        self.repo_root = (repo_root or REPO_ROOT).resolve()
        self.configs_root = (configs_root or CONFIGS_ROOT).resolve()

    def _resolve_path(self, config_path: str | Path) -> Path:
        path = Path(config_path)
        if not path.is_absolute():
            path = (self.repo_root / path).resolve()
        else:
            path = path.resolve()
        if not str(path).startswith(str(self.repo_root)):
            raise ValueError(f"config path must stay under project root: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"config not found: {path}")
        return path

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.repo_root).as_posix()

    def _path_info(self, path: Path) -> dict[str, Any]:
        rel = self._rel(path)
        writable = rel.startswith("configs/projects/") or (
            rel.startswith("out/") and path.name == "config_resolved.yaml"
        )
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
        if not rel.startswith("configs/projects/"):
            raise ValueError(f"config must live under configs/projects/: {rel}")
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
