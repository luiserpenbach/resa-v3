"""Bridge RESA engine results into the regen channel generator + solver."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..config.schema import ChamberConfig, EngineConfig
from ..regen_channels.config import RegenConfig
from ..regen_channels.contour import Contour, build_contour
from ..regen_channels.layout import ChannelLayout
from ..regen_channels.mesh import (
    build_channel_mesh,
    channel_centerline,
    centerlines_export_basename,
    html_3d_export_basename,
    mesh_export_basename,
    write_binary_stl,
    write_step,
)
from ..results import CombustionResult, ContourResult, ThrustChamberResult


@dataclass(frozen=True)
class RegenResult:
    """High-fidelity regen cooling analysis artifacts."""
    tag: str
    layout: ChannelLayout
    results: Optional[pd.DataFrame]
    files: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def summary(self) -> dict:
        d = {"tag": self.tag, "n_files": len(self.files)}
        if self.results is None:
            return d
        a = self.results.attrs
        d.update({
            "Q_total_kW": round(float(a["Q_total_kW"]), 2),
            "dp_bar": round(float(self.results.dp_cell_bar.sum()), 3),
            "outlet_T_K": round(float(a["outlet_T_K"]), 2),
            "outlet_p_bar": round(float(a["outlet_p_bar"]), 2),
            "T_wall_max_K": round(float(self.results.T_wall_hot_K.max()), 1),
            "saturation_reached": bool(a["saturation_reached"]),
        })
        return d


def contour_from_resa(cont: ContourResult) -> Contour:
    i = np.argsort(cont.x_m)
    return Contour(cont.x_m[i], cont.r_m[i])


def _build_contour(cfg: RegenConfig, res_contour: ContourResult) -> Contour:
    if cfg.contour.type == "from_engine":
        if cfg.sync.contour:
            return contour_from_resa(res_contour)
        raise ValueError(
            "contour.type=from_engine but sync.contour=false — set "
            "contour.type to parametric or points"
        )
    return build_contour(cfg.contour)


def prepare_regen_config(
    regen: RegenConfig,
    tc: ThrustChamberResult,
    comb: CombustionResult,
    chamber: ChamberConfig,
) -> RegenConfig:
    """Apply RESA nominal-point values for each sync flag that is enabled."""
    sync = regen.sync
    hot_updates: dict[str, float] = {}
    if sync.hot_gas_pc_bar:
        hot_updates["pc_bar"] = tc.pc_bar
    if sync.hot_gas_tc_K:
        hot_updates["tc_K"] = comb.tc_K
    if sync.hot_gas_gamma:
        hot_updates["gamma"] = comb.gamma
    if sync.hot_gas_mol_mass_kg_kmol:
        hot_updates["mol_mass_kg_kmol"] = comb.mw_kg_kmol
    if sync.hot_gas_c_star_m_s:
        hot_updates["c_star_m_s"] = comb.cstar_ideal_m_s
    if sync.hot_gas_bartz_correction:
        hot_updates["bartz_correction"] = chamber.bartz_correction

    hot = regen.solver.hot_gas.model_copy(update=hot_updates)
    solver_updates: dict = {"hot_gas": hot, "mdot_from_engine": sync.mdot}
    if sync.of_ratio:
        solver_updates["of_ratio"] = tc.of_ratio
    if sync.mdot:
        sol = regen.solver
        if sol.coolant_fraction is not None:
            mdot = tc.mdot_total_kg_s * sol.coolant_fraction
        elif sol.coolant_side == "fuel":
            mdot = tc.mdot_fuel_kg_s
        else:
            mdot = tc.mdot_ox_kg_s
        solver_updates["mdot_total"] = mdot
    solver = regen.solver.model_copy(update=solver_updates)
    return regen.model_copy(update={"solver": solver})


def run_regen(
    regen: RegenConfig,
    res_contour: ContourResult,
    out_dir: str | Path,
) -> RegenResult:
    """Run layout + optional solver and write the standard regen export set."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = regen.meta.name.replace(" ", "_")
    warnings: list[str] = []

    contour = _build_contour(regen, res_contour)
    lay = ChannelLayout(contour, regen)

    ch = regen.channels
    if regen.contour.type == "from_engine" and ch.start_x is not None and ch.start_x > -1e-6:
        warnings.append(
            f"regen: channels.start_x={ch.start_x * 1e3:.2f} mm is at or downstream "
            "of the throat (x=0). RESA engine contours put the chamber at x<0 — "
            "omit start_x for full axial coverage"
        )

    results = None
    if regen.solver.enabled:
        from ..regen_channels.solver import RegenSolver
        sol = RegenSolver(lay, regen)
        results = sol.solve()
        a = results.attrs
        if a["saturation_reached"]:
            warnings.append(
                "regen: bulk coolant reached saturation — two-phase bulk flow "
                "in part of the circuit"
            )
        if results.T_wall_hot_K.max() > regen.solver.wall.max_wall_temp_K:
            warnings.append(
                f"regen: hot wall exceeds "
                f"{regen.solver.wall.max_wall_temp_K:.0f} K limit"
            )

    files: list[str] = []
    e = regen.export.model_copy(update={"out_dir": str(out_dir)})
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
            warnings.append(
                "regen: STEP export skipped — pip install cadquery-ocp"
            )
    if e.html_3d:
        from ..regen_channels.viz import figure_3d
        ids = e.channel_ids(lay, "html_3d_channels")
        f = out_dir / html_3d_export_basename(tag, ids)
        figure_3d(
            lay, results, color_by=e.color_3d_by, channel_ids=ids
        ).write_html(str(f), include_plotlyjs=True)
        files.append(str(f))
    if e.html_plots:
        from ..regen_channels.viz import (
            figure_coolant_path, figure_geometry, figure_results,
        )
        f = out_dir / f"{tag}_geometry_plots.html"
        figure_geometry(lay).write_html(str(f), include_plotlyjs=True)
        files.append(str(f))
        if results is not None:
            f = out_dir / f"{tag}_results_plots.html"
            figure_results(
                results, lay, regen.solver.wall.max_wall_temp_K
            ).write_html(str(f), include_plotlyjs=True)
            files.append(str(f))
            f = out_dir / f"{tag}_coolant_path.html"
            figure_coolant_path(
                results, regen.solver.coolant,
            ).write_html(str(f), include_plotlyjs=True)
            files.append(str(f))

    return RegenResult(
        tag=tag, layout=lay, results=results,
        files=tuple(files), warnings=tuple(warnings),
    )


def run_regen_for_engine(
    cfg: EngineConfig,
    tc: ThrustChamberResult,
    comb: CombustionResult,
    res_contour: ContourResult,
    out_dir: str | Path,
) -> RegenResult:
    if cfg.regen is None:
        raise ValueError("engine config has no regen block")
    regen = prepare_regen_config(cfg.regen, tc, comb, cfg.chamber)
    return run_regen(regen, res_contour, out_dir)
