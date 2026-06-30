"""Single-command runner:  python -m resa.regen_channels.run config.yaml"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

from .config import RegenConfig
from .contour import build_contour
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


def run(config_path: str):
    cfg = RegenConfig.from_yaml(config_path)
    out = cfg.export.out_dir
    os.makedirs(out, exist_ok=True)
    tag = cfg.meta.name.replace(" ", "_")

    contour = build_contour(cfg.contour)
    lay = ChannelLayout(contour, cfg)
    print(f"[{tag}] contour x: {contour.x_min*1e3:.1f}..{contour.x_max*1e3:.1f} mm, "
          f"throat r = {lay.r_throat*1e3:.2f} mm @ x = {lay.x_throat*1e3:.1f} mm")
    print(f"[{tag}] {lay.N} channels, w {lay.w.min()*1e3:.2f}-{lay.w.max()*1e3:.2f} mm, "
          f"h {lay.h.min()*1e3:.2f}-{lay.h.max()*1e3:.2f} mm, "
          f"wrap {np.degrees(lay.theta[-1]):.1f} deg, "
          f"path length {lay.l[-1]*1e3:.1f} mm")

    results = None
    if cfg.solver.enabled:
        from .solver import RegenSolver
        sol = RegenSolver(lay, cfg)
        print(f"[{tag}] engine mdot {sol.hot.mdot:.3f} kg/s, "
              f"coolant mdot {sol.mdot_total:.3f} kg/s "
              f"({sol.mdot_ch*1e3:.1f} g/s per channel)")
        results = sol.solve()
        a = results.attrs
        print(f"[{tag}] Q_total {a['Q_total_kW']:.1f} kW | "
              f"dp {results.dp_cell_bar.sum():.2f} bar | "
              f"outlet {a['outlet_T_K']:.1f} K / {a['outlet_p_bar']:.1f} bar | "
              f"T_wall,max {results.T_wall_hot_K.max():.0f} K")
        if a["saturation_reached"]:
            print(f"[{tag}] WARNING: bulk coolant reached saturation — "
                  f"two-phase bulk flow in part of the circuit.")
        if results.T_wall_hot_K.max() > cfg.solver.wall.max_wall_temp_K:
            print(f"[{tag}] WARNING: hot wall exceeds "
                  f"{cfg.solver.wall.max_wall_temp_K:.0f} K limit.")

    files = []
    e = cfg.export
    if e.geometry_csv:
        f = os.path.join(out, f"{tag}_geometry.csv")
        lay.to_dataframe().to_csv(f, index=False)
        files.append(f)
    if e.results_csv and results is not None:
        f = os.path.join(out, f"{tag}_results.csv")
        results.to_csv(f, index=False)
        files.append(f)
    if e.centerlines_csv:
        cl_ids = e.channel_ids(lay, "centerlines_channels")
        rows = []
        for k in cl_ids:
            cl = channel_centerline(lay, k)
            rows.append(pd.DataFrame(
                {"channel": k, "x_mm": cl[:, 0] * 1e3,
                 "y_mm": cl[:, 1] * 1e3, "z_mm": cl[:, 2] * 1e3}))
        f = os.path.join(out, centerlines_export_basename(tag, cl_ids))
        pd.concat(rows).to_csv(f, index=False)
        files.append(f)
    if e.stl:
        ids = e.channel_ids(lay, "stl_channels")
        verts, faces, _ = build_channel_mesh(lay, ids)
        f = os.path.join(out, mesh_export_basename(tag, ids, "stl"))
        write_binary_stl(f, verts, faces)
        files.append(f)
    if e.step:
        ids = e.channel_ids(lay, "step_channels")
        f = os.path.join(out, mesh_export_basename(tag, ids, "step"))
        write_step(f, lay, ids, faceted=e.step_faceted)
        files.append(f)
    if e.html_3d:
        from .viz import figure_3d
        ids = e.channel_ids(lay, "html_3d_channels")
        fig = figure_3d(lay, results, color_by=e.color_3d_by, channel_ids=ids)
        f = os.path.join(out, html_3d_export_basename(tag, ids))
        fig.write_html(f, include_plotlyjs=True)
        files.append(f)
    if e.html_plots:
        from .viz import figure_coolant_path, figure_geometry, figure_results
        f = os.path.join(out, f"{tag}_geometry_plots.html")
        figure_geometry(lay).write_html(f, include_plotlyjs=True)
        files.append(f)
        if results is not None:
            f = os.path.join(out, f"{tag}_results_plots.html")
            figure_results(results, lay,
                           cfg.solver.wall.max_wall_temp_K).write_html(
                f, include_plotlyjs=True)
            files.append(f)
            f = os.path.join(out, f"{tag}_coolant_path.html")
            figure_coolant_path(results, cfg.solver.coolant).write_html(
                f, include_plotlyjs=True)
            files.append(f)
    print(f"[{tag}] wrote:")
    for f in files:
        print("   ", f)
    return lay, results, files


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m resa.regen_channels.run <config.yaml>")
    run(sys.argv[1])
