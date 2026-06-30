"""Campaign runner: orchestrate multi-config report generation from YAML."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config.loader import load_config
from .pipeline import run
from .regen.integration import contour_from_resa, prepare_regen_config
from .regen_channels.diff import figure_diff
from .regen_channels.layout import ChannelLayout
from .reporting.diff import diff_folders
from .reporting.report import write_report


@dataclass(frozen=True)
class PairDiffSpec:
    a: str
    b: str
    output: str


@dataclass(frozen=True)
class CampaignSpec:
    name: str
    output: str
    configs: list[str]
    rollup: bool = True
    diffs: tuple[PairDiffSpec, ...] = ()
    regen_diffs: tuple[PairDiffSpec, ...] = ()


def _resolve(path: str, base: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str((base / p).resolve())


def load_campaign(path: str | Path) -> CampaignSpec:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)
    base = path.parent

    def pairs(key: str) -> tuple[PairDiffSpec, ...]:
        items = raw.get(key) or []
        return tuple(
            PairDiffSpec(
                a=_resolve(item["a"], base),
                b=_resolve(item["b"], base),
                output=item["output"],
            )
            for item in items
        )

    return CampaignSpec(
        name=str(raw.get("name", path.stem)),
        output=str(raw.get("output", "out")),
        configs=[_resolve(c, base) for c in raw["configs"]],
        rollup=bool(raw.get("rollup", True)),
        diffs=pairs("diffs"),
        regen_diffs=pairs("regen_diffs"),
    )


def _write_rollup(summaries: list[dict], path: Path) -> None:
    keys = list({k for row in summaries for k in row})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(summaries)


def _regen_diff_html(cfg_a_path: str, cfg_b_path: str, res_a, res_b, path: Path) -> str | None:
    cfg_a = load_config(cfg_a_path)
    cfg_b = load_config(cfg_b_path)
    if cfg_a.regen is None or cfg_b.regen is None:
        missing = []
        if cfg_a.regen is None:
            missing.append(cfg_a_path)
        if cfg_b.regen is None:
            missing.append(cfg_b_path)
        return (
            f"regen diff skipped — no regen block in: {', '.join(missing)}"
        )
    regen_a = prepare_regen_config(
        cfg_a.regen, res_a.thrust_chamber, res_a.combustion, cfg_a.chamber)
    regen_b = prepare_regen_config(
        cfg_b.regen, res_b.thrust_chamber, res_b.combustion, cfg_b.chamber)
    lay_a = ChannelLayout(contour_from_resa(res_a.contour), regen_a)
    lay_b = ChannelLayout(contour_from_resa(res_b.contour), regen_b)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure_diff(
        lay_a, lay_b, None, None, regen_a.meta.name, regen_b.meta.name,
    ).write_html(str(path), include_plotlyjs="cdn")
    return None


def run_campaign(
    campaign_path: str | Path,
    *,
    out_root: str | Path | None = None,
    verbose: bool = True,
) -> Path:
    """Run all configs in a campaign file; return output root directory."""
    spec = load_campaign(campaign_path)
    out_root = Path(out_root or spec.output)
    out_root.mkdir(parents=True, exist_ok=True)

    summaries: list[dict] = []
    outdirs: dict[str, Path] = {}
    results: dict[str, Any] = {}

    if verbose:
        print(f"Campaign {spec.name!r} -> {out_root.resolve()}/\n")

    for cfg_path in spec.configs:
        cfg = load_config(cfg_path)
        res = run(cfg)
        outdir, res = write_report(res, cfg, cfg_path, out_root=out_root)
        outdirs[cfg_path] = outdir
        results[cfg_path] = res
        summaries.append(res.summary())
        if verbose:
            print(f"  {cfg_path}")
            print(f"    -> {outdir.name}/")
            if res.regen is not None:
                print(f"    regen: {len(res.regen.files)} files ({res.regen.tag}_*)")
            print(f"    {json.dumps(res.summary(), indent=2)}\n")

    if spec.rollup and summaries:
        rollup_path = out_root / "campaign_rollup.csv"
        _write_rollup(summaries, rollup_path)
        if verbose:
            print(f"rollup -> {rollup_path}\n")

    for diff in spec.diffs:
        if diff.a not in outdirs or diff.b not in outdirs:
            raise ValueError(
                f"diff {diff.output!r} references configs not in campaign "
                f"configs list: {diff.a!r}, {diff.b!r}")
        text = diff_folders(outdirs[diff.a], outdirs[diff.b])
        out_path = out_root / diff.output
        out_path.write_text(text, encoding="utf-8")
        if verbose:
            print(f"diff   -> {out_path}")
            print()
            print(text)

    for diff in spec.regen_diffs:
        if diff.a not in results or diff.b not in results:
            raise ValueError(
                f"regen_diff {diff.output!r} references configs not in campaign "
                f"configs list")
        out_path = out_root / diff.output
        note = _regen_diff_html(diff.a, diff.b, results[diff.a], results[diff.b], out_path)
        if note:
            if verbose:
                print(f"regen  (skipped) {note}")
        elif verbose:
            print(f"regen  -> {out_path}")

    return out_root
