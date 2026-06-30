"""Write standard regen export artifacts (CSV, STL, STEP, Plotly HTML)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import ExportCfg, RegenConfig
from .layout import ChannelLayout
from .mesh import (
    build_channel_mesh,
    channel_centerline,
    centerlines_export_basename,
    html_3d_export_basename,
    mesh_export_basename,
    write_binary_stl,
    write_step,
)

_PLOTLY_JS = "cdn"


def export_artifacts(
    lay: ChannelLayout,
    cfg: RegenConfig,
    results: pd.DataFrame | None,
    *,
    out_dir: str | Path,
    tag: str | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Write enabled export artifacts. Returns ``(file_paths, warnings)``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = tag or cfg.meta.name.replace(" ", "_")
    e: ExportCfg = cfg.export.model_copy(update={"out_dir": str(out_dir)})

    files: list[str] = []
    warnings: list[str] = []

    if e.geometry_csv:
        f = out_dir / f"{tag}_geometry.csv"
        lay.to_dataframe().to_csv(f, index=False)
        files.append(str(f))
    if e.results_csv and results is not None:
        f = out_dir / f"{tag}_results.csv"
        results.to_csv(f, index=False)
        files.append(str(f))
    if e.centerlines_csv:
        cl_ids = e.channel_ids(lay, "centerlines_channels")
        rows = []
        for k in cl_ids:
            cl = channel_centerline(lay, k)
            rows.append(pd.DataFrame({
                "channel": k,
                "x_mm": cl[:, 0] * 1e3,
                "y_mm": cl[:, 1] * 1e3,
                "z_mm": cl[:, 2] * 1e3,
            }))
        f = out_dir / centerlines_export_basename(tag, cl_ids)
        pd.concat(rows).to_csv(f, index=False)
        files.append(str(f))
    if e.stl:
        ids = e.channel_ids(lay, "stl_channels")
        verts, faces, _ = build_channel_mesh(lay, ids)
        f = out_dir / mesh_export_basename(tag, ids, "stl")
        write_binary_stl(str(f), verts, faces)
        files.append(str(f))
    if e.step:
        try:
            ids = e.channel_ids(lay, "step_channels")
            f = out_dir / mesh_export_basename(tag, ids, "step")
            write_step(str(f), lay, ids, faceted=e.step_faceted)
            files.append(str(f))
        except ImportError:
            warnings.append("regen: STEP export skipped — pip install cadquery-ocp")
    if e.html_3d:
        from .viz import figure_3d
        ids = e.channel_ids(lay, "html_3d_channels")
        f = out_dir / html_3d_export_basename(tag, ids)
        figure_3d(
            lay, results, color_by=e.color_3d_by, channel_ids=ids,
        ).write_html(str(f), include_plotlyjs=_PLOTLY_JS)
        files.append(str(f))
    if e.html_plots:
        from .viz import figure_coolant_path, figure_geometry, figure_results
        f = out_dir / f"{tag}_geometry_plots.html"
        figure_geometry(lay).write_html(str(f), include_plotlyjs=_PLOTLY_JS)
        files.append(str(f))
        if results is not None:
            f = out_dir / f"{tag}_results_plots.html"
            figure_results(
                results, lay, cfg.solver.wall.max_wall_temp_K,
            ).write_html(str(f), include_plotlyjs=_PLOTLY_JS)
            files.append(str(f))
            f = out_dir / f"{tag}_coolant_path.html"
            figure_coolant_path(
                results, cfg.solver.coolant,
            ).write_html(str(f), include_plotlyjs=_PLOTLY_JS)
            files.append(str(f))

    return tuple(files), tuple(warnings)
