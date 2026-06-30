"""Load + compose YAML into a validated EngineConfig.

Supports file references: any string field whose value ends in .yaml is loaded
and spliced in, so the team can keep prop/chamber/cooling in separate files
owned by separate people.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .schema import EngineConfig

_REF_KEYS = {"propellants", "combustion", "chamber", "cooling", "regen"}


def _deep_merge(base: dict, override: dict) -> dict:
    """Override wins; dicts merge recursively; explicit null clears a key."""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_raw(path: Path) -> dict[str, Any]:
    """Load YAML, resolving `base:` inheritance (recursively) and file refs."""
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    base_ref = raw.pop("base", None)
    raw = _resolve_refs(raw, path.parent)
    if base_ref is not None:
        base = _load_raw((path.parent / base_ref).resolve())
        raw = _deep_merge(base, raw)
    return raw


def _resolve_refs(data: dict[str, Any], base: Path) -> dict[str, Any]:
    """Replace 'key: some/file.yaml' with the parsed contents of that file."""
    out = dict(data)
    for key in _REF_KEYS:
        val = out.get(key)
        if isinstance(val, str) and val.endswith((".yaml", ".yml")):
            ref_path = (base / val).resolve()
            with ref_path.open(encoding="utf-8") as f:
                out[key] = yaml.safe_load(f)
    return out


def _hash(data: dict[str, Any]) -> str:
    blob = json.dumps(data, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def load_resolved_dict(path: str | Path) -> dict[str, Any]:
    """Load YAML with ``base:`` inheritance and file refs fully resolved."""
    return _load_raw(Path(path))


def read_raw_config(path: str | Path) -> dict[str, Any]:
    """Load YAML exactly as written on disk (no ``base:`` merge)."""
    with Path(path).open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return raw if isinstance(raw, dict) else {}


def load_inherited_dict(path: str | Path) -> dict[str, Any]:
    """Resolved config inherited via ``base:`` only (excludes this file's overlay)."""
    path = Path(path)
    raw = read_raw_config(path)
    base_ref = raw.get("base")
    if not base_ref:
        return {}
    return load_resolved_dict((path.parent / base_ref).resolve())


def resolve_file_ref(value: Any, base_dir: Path) -> Any:
    """If *value* is a ``.yaml`` path string, load and return its contents."""
    if isinstance(value, str) and value.endswith((".yaml", ".yml")):
        ref_path = (base_dir / value).resolve()
        with ref_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    return value


def load_config(path: str | Path) -> EngineConfig:
    path = Path(path)
    resolved = _load_raw(path)
    cfg = EngineConfig.model_validate(resolved)
    # frozen model → rebuild with hash attached
    return cfg.model_copy(update={"config_hash": _hash(resolved)})
