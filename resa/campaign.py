"""Campaign runner: orchestrate multi-config report generation from YAML.

Besides explicit ``configs:`` lists, a campaign can define a parametric
design sweep: a ``base:`` engine config plus ``sweep:`` axes (dotted config
paths mapped to value lists or ``{range: [lo, hi], n: N}``). The cross
product of all axes is run through the fast pipeline, each row tagged with
its axis values in ``sweep_rollup.csv``, with optional regen thermal KPIs
(``sweep_regen: true``) and 1D/2D plots when plotly is available.
"""
from __future__ import annotations

import copy
import csv
import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .config.loader import load_config, load_resolved_dict
from .config.schema import EngineConfig
from .paths import confined_relative
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
    base: str | None = None
    sweep: tuple[tuple[str, tuple[float, ...]], ...] = ()
    sweep_regen: bool = False


_MAX_SWEEP_POINTS = 1000


def _sweep_axis_values(spec: Any) -> tuple[float, ...]:
    """Normalize one sweep axis: value list, or {range: [lo, hi], n: N}."""
    if isinstance(spec, dict):
        if "range" in spec:
            lo, hi = spec["range"]
            n = int(spec.get("n", 5))
            if n < 2:
                raise ValueError("sweep axis range needs n >= 2")
            return tuple(float(v) for v in np.linspace(lo, hi, n))
        if "values" in spec:
            return tuple(float(v) for v in spec["values"])
        raise ValueError(f"sweep axis needs 'range' or 'values', got {spec!r}")
    if isinstance(spec, (list, tuple)):
        return tuple(float(v) for v in spec)
    raise ValueError(f"sweep axis must be a list or range mapping, got {spec!r}")


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

    sweep_raw = raw.get("sweep") or {}
    sweep = tuple(
        (str(axis), _sweep_axis_values(vals)) for axis, vals in sweep_raw.items()
    )
    sweep_base = raw.get("base")
    if sweep and not sweep_base:
        raise ValueError("campaign 'sweep' requires a 'base' config path")
    n_points = 1
    for _, vals in sweep:
        n_points *= len(vals)
    if sweep and n_points > _MAX_SWEEP_POINTS:
        raise ValueError(
            f"sweep grid has {n_points} points (max {_MAX_SWEEP_POINTS})")

    configs_raw = raw.get("configs") or []
    if not configs_raw and not sweep:
        raise ValueError("campaign needs 'configs' and/or 'base' + 'sweep'")

    return CampaignSpec(
        name=str(raw.get("name", path.stem)),
        output=str(raw.get("output", "out")),
        configs=[_resolve(c, base) for c in configs_raw],
        rollup=bool(raw.get("rollup", True)),
        diffs=pairs("diffs"),
        regen_diffs=pairs("regen_diffs"),
        base=_resolve(sweep_base, base) if sweep_base else None,
        sweep=sweep,
        sweep_regen=bool(raw.get("sweep_regen", False)),
    )


def _write_rollup(summaries: list[dict], path: Path) -> None:
    # deterministic column order (insertion order across rows), so rollup
    # CSVs diff cleanly between runs
    keys = list(dict.fromkeys(k for row in summaries for k in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(summaries)


def _set_by_path(d: dict, dotted: str, value: Any) -> None:
    """Set ``d['a']['b']['c'] = value`` for dotted path ``a.b.c``."""
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[keys[-1]] = value


def _regen_kpis(cfg: EngineConfig, res) -> dict[str, Any]:
    """Solve the regen circuit for one sweep point; no file artifacts."""
    from .regen.integration import _build_contour
    from .regen_channels.solver import RegenSolver

    regen = prepare_regen_config(
        cfg.regen, res.thrust_chamber, res.combustion, cfg.chamber,
        film=cfg.film_cooling)
    if not regen.solver.enabled:
        return {}
    lay = ChannelLayout(_build_contour(regen, res.contour), regen)
    df = RegenSolver(lay, regen).solve()
    return {
        "T_wall_max_K": round(float(df.T_wall_hot_K.max()), 1),
        "dp_regen_bar": round(float(df.dp_cell_bar.sum()), 3),
        "Q_total_kW": round(float(df.attrs["Q_total_kW"]), 2),
    }


def _run_sweep(spec: CampaignSpec, out_root: Path, verbose: bool) -> list[dict]:
    """Cross-product sweep over spec.sweep axes applied to spec.base."""
    base_dict = load_resolved_dict(spec.base)
    axis_names = [name for name, _ in spec.sweep]
    rows: list[dict] = []
    for combo in itertools.product(*(vals for _, vals in spec.sweep)):
        point = copy.deepcopy(base_dict)
        for name, val in zip(axis_names, combo):
            _set_by_path(point, name, val)
        row: dict[str, Any] = {name: val for name, val in zip(axis_names, combo)}
        try:
            cfg = EngineConfig.model_validate(point)
            res = run(cfg)
            row.update(res.summary())
            if spec.sweep_regen and cfg.regen is not None:
                row.update(_regen_kpis(cfg, res))
        except Exception as exc:
            # one infeasible point must not kill the study
            row["error"] = str(exc)[:300]
        rows.append(row)
        if verbose:
            tag = ", ".join(f"{n}={v:g}" for n, v in zip(axis_names, combo))
            status = row.get("error") or f"isp={row.get('isp_s')}"
            print(f"  sweep [{tag}] -> {status}")
    return rows


def _write_sweep_plots(spec: CampaignSpec, rows: list[dict], out_root: Path) -> Path | None:
    """1 axis → metric lines; 2 axes → heatmaps. Needs plotly; else skipped."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return None
    axes = [name for name, _ in spec.sweep]
    ok_rows = [r for r in rows if "error" not in r]
    if not ok_rows or len(axes) > 2:
        return None
    metrics = [m for m in ("isp_s", "thrust_N", "T_wall_max_K", "dp_regen_bar")
               if any(r.get(m) is not None for r in ok_rows)]
    if not metrics:
        return None
    path = out_root / "sweep_plots.html"

    if len(axes) == 1:
        ax = axes[0]
        fig = make_subplots(rows=len(metrics), cols=1, shared_xaxes=True,
                            subplot_titles=metrics)
        for i, m in enumerate(metrics, start=1):
            pts = [(r[ax], r[m]) for r in ok_rows if r.get(m) is not None]
            pts.sort()
            fig.add_trace(
                go.Scatter(x=[p[0] for p in pts], y=[p[1] for p in pts],
                           mode="lines+markers", name=m),
                row=i, col=1)
        fig.update_xaxes(title_text=ax, row=len(metrics))
        fig.update_layout(title=f"Sweep: {spec.name}", template="plotly_white",
                          height=240 * len(metrics), showlegend=False)
    else:
        ax_x, ax_y = axes[1], axes[0]   # first axis varies slowest → rows
        xs = sorted({r[ax_x] for r in ok_rows})
        ys = sorted({r[ax_y] for r in ok_rows})
        fig = make_subplots(rows=1, cols=len(metrics), subplot_titles=metrics)
        for i, m in enumerate(metrics, start=1):
            grid = [[next((r[m] for r in ok_rows
                           if r[ax_x] == x and r[ax_y] == y and r.get(m) is not None),
                          None)
                     for x in xs] for y in ys]
            fig.add_trace(
                go.Heatmap(x=xs, y=ys, z=grid, coloraxis=None,
                           colorbar=dict(title=m, len=0.8) if i == len(metrics) else None,
                           showscale=(i == len(metrics))),
                row=1, col=i)
            fig.update_xaxes(title_text=ax_x, row=1, col=i)
        fig.update_yaxes(title_text=ax_y, row=1, col=1)
        fig.update_layout(title=f"Sweep: {spec.name}", template="plotly_white",
                          height=460)

    fig.write_html(str(path), include_plotlyjs="cdn")
    return path


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

    if spec.sweep:
        if verbose:
            n_pts = 1
            for _, vals in spec.sweep:
                n_pts *= len(vals)
            print(f"sweep  {n_pts} points over "
                  f"{', '.join(name for name, _ in spec.sweep)}")
        sweep_rows = _run_sweep(spec, out_root, verbose)
        sweep_path = out_root / "sweep_rollup.csv"
        _write_rollup(sweep_rows, sweep_path)
        if verbose:
            print(f"sweep  -> {sweep_path}")
        plot_path = _write_sweep_plots(spec, sweep_rows, out_root)
        if verbose and plot_path:
            print(f"sweep  -> {plot_path}")

    for diff in spec.diffs:
        if diff.a not in outdirs or diff.b not in outdirs:
            raise ValueError(
                f"diff {diff.output!r} references configs not in campaign "
                f"configs list: {diff.a!r}, {diff.b!r}")
        text = diff_folders(outdirs[diff.a], outdirs[diff.b])
        out_path = confined_relative(diff.output, out_root)
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
        out_path = confined_relative(diff.output, out_root)
        note = _regen_diff_html(diff.a, diff.b, results[diff.a], results[diff.b], out_path)
        if note:
            if verbose:
                print(f"regen  (skipped) {note}")
        elif verbose:
            print(f"regen  -> {out_path}")

    return out_root
