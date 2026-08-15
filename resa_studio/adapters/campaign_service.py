"""Campaign listing and execution for RESA Studio."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from resa.campaign import load_campaign, run_campaign
from resa.paths import safe_output_name

from ..settings import OUT_ROOT, REPO_ROOT, rel_to


class CampaignService:
    def __init__(
        self,
        repo_root: Path | None = None,
        out_root: Path | None = None,
    ) -> None:
        self.repo_root = (repo_root or REPO_ROOT).resolve()
        self.out_root = (out_root or OUT_ROOT).resolve()
        self.campaigns_root = self.repo_root / "campaigns"

    def _resolve_campaign(self, campaign_path: str) -> Path:
        path = Path(campaign_path)
        if not path.is_absolute():
            path = (self.repo_root / path).resolve()
        else:
            path = path.resolve()
        if not path.is_relative_to(self.campaigns_root):
            raise ValueError("campaign path must stay under campaigns/")
        if not path.is_file():
            raise FileNotFoundError(f"campaign not found: {campaign_path}")
        return path

    def _campaign_out_dir(self, spec) -> Path:
        name = safe_output_name(Path(spec.output).name or spec.name, fallback=spec.name)
        return self.out_root / name

    def list_campaigns(self) -> list[dict[str, str]]:
        if not self.campaigns_root.is_dir():
            return []
        items: list[dict[str, str]] = []
        for path in sorted(self.campaigns_root.rglob("*.yaml")):
            rel = path.relative_to(self.repo_root).as_posix()
            try:
                spec = load_campaign(path)
                name = spec.name
                n_configs = len(spec.configs)
            except Exception:
                name = path.stem
                n_configs = 0
            items.append({
                "path": rel,
                "name": name,
                "n_configs": str(n_configs),
            })
        return items

    def run(self, campaign_path: str) -> dict[str, Any]:
        path = self._resolve_campaign(campaign_path)
        spec = load_campaign(path)
        dest = self._campaign_out_dir(spec)
        dest.mkdir(parents=True, exist_ok=True)
        out_root = run_campaign(path, out_root=dest, verbose=False)
        rel_out = rel_to(out_root, self.repo_root)
        artifacts = sorted(
            p.relative_to(out_root).as_posix()
            for p in out_root.rglob("*")
            if p.is_file()
        )
        return {
            "ok": True,
            "name": spec.name,
            "campaign_path": rel_to(path, self.repo_root),
            "outdir": rel_out,
            "n_configs": len(spec.configs),
            "artifacts": artifacts[:200],
        }
