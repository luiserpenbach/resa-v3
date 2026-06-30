"""Single-command runner:  python -m resa.regen_channels.run config.yaml"""
from __future__ import annotations

import os
import sys

import numpy as np

from .config import RegenConfig
from .contour import build_contour
from .export import export_artifacts
from .layout import ChannelLayout


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

    files, warnings = export_artifacts(lay, cfg, results, out_dir=out, tag=tag)
    for msg in warnings:
        print(f"[{tag}] WARNING: {msg}")
    print(f"[{tag}] wrote:")
    for f in files:
        print("   ", f)
    return lay, results, files


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m resa.regen_channels.run <config.yaml>")
    run(sys.argv[1])
