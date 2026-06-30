"""Campaign listing and execution for RESA Studio."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from resa.campaign import load_campaign, run_campaign

from ..settings import OUT_ROOT, REPO_ROOT


class CampaignService:
    def __init__(
        self,
        repo_root: Path | None = None,
        out_root: Path | None = None,
    ) -> None:
        self.repo_root = (repo_root or REPO_ROOT).resolve()
        self.out_root = (out_root or OUT_ROOT).resolve()
        self.campaigns_root = self.repo_root / "campaigns"

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
        path = Path(campaign_path)
        if not path.is_absolute():
            path = (self.repo_root / path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"campaign not found: {campaign_path}")
        spec = load_campaign(path)
        out_root = run_campaign(path, out_root=self.out_root, verbose=False)
        rel_out = out_root.relative_to(self.repo_root).as_posix()
        artifacts = sorted(
            p.relative_to(out_root).as_posix()
            for p in out_root.rglob("*")
            if p.is_file()
        )
        return {
            "ok": True,
            "name": spec.name,
            "campaign_path": path.relative_to(self.repo_root).as_posix(),
            "outdir": rel_out,
            "n_configs": len(spec.configs),
            "artifacts": artifacts[:200],
        }
