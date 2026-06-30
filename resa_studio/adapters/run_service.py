"""Run orchestration — wraps pipeline + reporting."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from resa.config.schema import EngineConfig
from resa.pipeline import run as pipeline_run
from resa.reporting.report import write_report

from ..settings import OUT_ROOT, REPO_ROOT
from .config_service import ConfigService
from .result_serializer import result_to_dict


@dataclass(frozen=True)
class RunOutput:
    mode: Literal["fast", "full"]
    config: EngineConfig
    config_path: str | None
    outdir: Path | None
    result: dict[str, Any]
    artifacts: tuple[str, ...]


class RunService:
    def __init__(
        self,
        config_service: ConfigService | None = None,
        out_root: Path | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.configs = config_service or ConfigService()
        self.out_root = (out_root or OUT_ROOT).resolve()
        self.repo_root = (repo_root or REPO_ROOT).resolve()

    def _resolve_cfg(
        self,
        *,
        config_path: str | None,
        config: dict[str, Any] | None,
    ) -> tuple[EngineConfig, Path | None]:
        if (config_path is None) == (config is None):
            raise ValueError("give exactly one of config_path or config")
        if config_path is not None:
            cfg, path = self.configs.load_path(config_path)
            return cfg, path
        return self.configs.validate_dict(config), None

    def run_fast(
        self,
        *,
        config_path: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> RunOutput:
        cfg, path = self._resolve_cfg(config_path=config_path, config=config)
        res = pipeline_run(cfg)
        return RunOutput(
            mode="fast",
            config=cfg,
            config_path=str(path.relative_to(self.repo_root)).replace("\\", "/")
            if path else None,
            outdir=None,
            result=result_to_dict(res),
            artifacts=(),
        )

    def run_full(
        self,
        *,
        config_path: str | None = None,
        config: dict[str, Any] | None = None,
        out_root: Path | None = None,
    ) -> RunOutput:
        cfg, path = self._resolve_cfg(config_path=config_path, config=config)
        res = pipeline_run(cfg)
        root = (out_root or self.out_root).resolve()
        cfg_path = path or "(inline)"
        outdir, res = write_report(res, cfg, cfg_path, out_root=root)
        artifacts = tuple(
            sorted(p.relative_to(outdir).as_posix() for p in outdir.rglob("*") if p.is_file())
        )
        return RunOutput(
            mode="full",
            config=cfg,
            config_path=str(path.relative_to(self.repo_root)).replace("\\", "/")
            if path else None,
            outdir=outdir,
            result=result_to_dict(res),
            artifacts=artifacts,
        )

    def list_runs(self) -> list[dict[str, Any]]:
        """Scan out/ for completed report folders (must contain results.yaml)."""
        if not self.out_root.is_dir():
            return []
        runs: list[dict[str, Any]] = []
        for outdir in self.out_root.iterdir():
            if not outdir.is_dir():
                continue
            results_path = outdir / "results.yaml"
            if not results_path.is_file():
                continue
            name = outdir.name
            idx = name.rfind("_")
            if idx <= 0:
                continue
            engine, config_hash = name[:idx], name[idx + 1 :]
            import yaml

            with results_path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            tc = data.get("thrust_chamber") or {}
            runs.append({
                "engine": engine,
                "config_hash": config_hash,
                "outdir": str(outdir.relative_to(self.repo_root)).replace("\\", "/"),
                "mode": data.get("mode", "full"),
                "thrust_N": tc.get("thrust_N"),
                "isp_s": tc.get("isp_s"),
                "modified_at": outdir.stat().st_mtime,
            })
        runs.sort(key=lambda r: r["modified_at"], reverse=True)
        return runs

    @staticmethod
    def _summary_from_results(data: dict[str, Any]) -> dict[str, Any]:
        tc = data.get("thrust_chamber") or {}
        comb = data.get("combustion") or {}
        p = tc.get("provenance") or {}
        return {
            "engine": data.get("engine"),
            "config_hash": data.get("config_hash"),
            "mode": data.get("mode"),
            "cstar_source": comb.get("source"),
            "thrust_N": round(tc["thrust_N"], 1) if tc.get("thrust_N") is not None else None,
            "thrust_src": p.get("thrust", "?"),
            "pc_bar": round(tc["pc_bar"], 3) if tc.get("pc_bar") is not None else None,
            "pc_src": p.get("pc", "?"),
            "of_ratio": round(tc["of_ratio"], 3) if tc.get("of_ratio") is not None else None,
            "of_src": p.get("of_ratio", "?"),
            "eps": round(tc["eps"], 3) if tc.get("eps") is not None else None,
            "eps_src": p.get("eps", "?"),
            "mdot_kg_s": round(tc["mdot_total_kg_s"], 4)
            if tc.get("mdot_total_kg_s") is not None
            else None,
            "isp_s": round(tc["isp_s"], 2) if tc.get("isp_s") is not None else None,
            "cf": round(tc["cf"], 4) if tc.get("cf") is not None else None,
            "throat_r_mm": round(tc["throat_radius_m"] * 1e3, 3)
            if tc.get("throat_radius_m") is not None
            else None,
            "tc_K": round(comb["tc_K"], 1) if comb.get("tc_K") is not None else None,
            "separated": tc.get("separated"),
            "n_warnings": len(data.get("warnings") or []),
        }

    def load_existing(self, engine: str, config_hash: str) -> dict[str, Any] | None:
        outdir = self.out_root / f"{engine}_{config_hash}"
        results_path = outdir / "results.yaml"
        if not results_path.is_file():
            return None
        import yaml

        with results_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        artifacts = tuple(
            sorted(p.relative_to(outdir).as_posix() for p in outdir.rglob("*") if p.is_file())
        )
        tc = data.get("thrust_chamber") or {}

        analysis_mode = data.get("mode", "design")
        config_dict: dict[str, Any] | None = None
        config_source: str | None = None
        cfg_resolved = outdir / "config_resolved.yaml"
        if cfg_resolved.is_file():
            with cfg_resolved.open(encoding="utf-8") as f:
                config_dict = yaml.safe_load(f) or {}
            config_source = str(cfg_resolved.relative_to(self.repo_root)).replace("\\", "/")
            try:
                cfg = EngineConfig.model_validate(config_dict)
                analysis_mode = cfg.mode
            except Exception:
                config_dict = None
                config_source = None

        path_info: dict[str, Any] = {}
        if config_source:
            path_info = ConfigService(self.repo_root).path_info(config_source)

        return {
            "mode": data.get("mode", "full"),
            "engine": engine,
            "config_hash": config_hash,
            "analysis_mode": analysis_mode,
            "config": config_dict,
            "config_source": config_source,
            **path_info,
            "outdir": str(outdir.relative_to(self.repo_root)).replace("\\", "/"),
            "summary": self._summary_from_results(data),
            "warnings": list(data.get("warnings") or []),
            "provenance": dict(tc.get("provenance") or {}),
            "artifacts": list(artifacts),
            "results": data,
            "offdesign": data.get("offdesign"),
            "regen": data.get("regen"),
        }
