"""Compare saved runs and config dicts for the studio UI."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from resa.reporting.diff import diff_dicts

from ..settings import OUT_ROOT, REPO_ROOT


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _rows_to_json(rows: list[tuple]) -> list[dict[str, str]]:
    return [
        {"key": r[0], "a": r[1], "b": r[2], "delta": r[3]}
        for r in rows
    ]


class CompareService:
    def __init__(
        self,
        out_root: Path | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.out_root = (out_root or OUT_ROOT).resolve()
        self.repo_root = (repo_root or REPO_ROOT).resolve()

    def _run_dir(self, engine: str, config_hash: str) -> Path:
        return self.out_root / f"{engine}_{config_hash}"

    def compare_runs(
        self,
        engine_a: str,
        config_hash_a: str,
        engine_b: str,
        config_hash_b: str,
    ) -> dict[str, Any]:
        dir_a = self._run_dir(engine_a, config_hash_a)
        dir_b = self._run_dir(engine_b, config_hash_b)
        if not dir_a.is_dir():
            raise FileNotFoundError(f"run not found: {engine_a}_{config_hash_a}")
        if not dir_b.is_dir():
            raise FileNotFoundError(f"run not found: {engine_b}_{config_hash_b}")

        cfg_a = _load_yaml(dir_a / "config_resolved.yaml")
        cfg_b = _load_yaml(dir_b / "config_resolved.yaml")
        res_a = _load_yaml(dir_a / "results.yaml")
        res_b = _load_yaml(dir_b / "results.yaml")

        warn_a = set(res_a.pop("warnings", []) or [])
        warn_b = set(res_b.pop("warnings", []) or [])

        return {
            "a": {
                "engine": res_a.get("engine", engine_a),
                "config_hash": res_a.get("config_hash", config_hash_a),
                "outdir": str(dir_a.relative_to(self.repo_root)).replace("\\", "/"),
                "mode": res_a.get("mode"),
            },
            "b": {
                "engine": res_b.get("engine", engine_b),
                "config_hash": res_b.get("config_hash", config_hash_b),
                "outdir": str(dir_b.relative_to(self.repo_root)).replace("\\", "/"),
                "mode": res_b.get("mode"),
            },
            "config_diff": _rows_to_json(diff_dicts(cfg_a, cfg_b)),
            "result_diff": _rows_to_json(diff_dicts(res_a, res_b)),
            "warnings_resolved": sorted(warn_a - warn_b),
            "warnings_new": sorted(warn_b - warn_a),
        }

    def compare_configs(
        self,
        config_a: dict[str, Any],
        config_b: dict[str, Any],
    ) -> dict[str, Any]:
        a = dict(config_a)
        b = dict(config_b)
        a.pop("config_hash", None)
        b.pop("config_hash", None)
        return {
            "config_diff": _rows_to_json(diff_dicts(a, b)),
        }
