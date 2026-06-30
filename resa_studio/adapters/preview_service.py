"""Live geometry previews for the design workspace (contour, cooling layout, export)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import ValidationError

from resa.config.schema import EngineConfig
from resa.regen.integration import contour_from_resa, prepare_regen_config
from resa.regen_channels.config import (
    ChannelsCfg,
    ContourCfg,
    CoolantInletCfg,
    EngineSyncCfg,
    MetaCfg,
    RegenConfig,
    RibCfg,
    SolverCfg,
)
from resa.regen_channels.layout import ChannelLayout
from resa.regen_channels.mesh import build_channel_mesh, write_binary_stl, write_step

from resa_studio.adapters.preview_cache import PIPELINE_CACHE


def _validate_config(data: dict[str, Any]) -> EngineConfig:
    return EngineConfig.model_validate(data)


def _pipeline_result(data: dict[str, Any]):
    """Run (or reuse cached) full engine pipeline for preview endpoints."""
    return PIPELINE_CACHE.get_or_run(data, _validate_config)


def preview_cache_stats() -> dict[str, Any]:
    return PIPELINE_CACHE.stats()


def _contour_payload(cont) -> dict[str, Any]:
    i = np.argsort(cont.x_m)
    x = cont.x_m[i].tolist()
    r = cont.r_m[i].tolist()
    return {
        "x_m": x,
        "r_m": r,
        "dimensions": {
            "chamber_radius_m": cont.chamber_radius_m,
            "chamber_length_m": cont.chamber_length_m,
            "convergent_length_m": cont.convergent_length_m,
            "divergent_length_m": cont.divergent_length_m,
            "throat_radius_m": cont.throat_radius_m,
            "exit_radius_m": cont.exit_radius_m,
            "contraction_ratio": cont.contraction_ratio,
            "eps": cont.eps,
            "theta_n_deg": cont.theta_n_deg,
            "theta_e_deg": cont.theta_e_deg,
            "conv_entrance_radius_m": cont.conv_entrance_radius_m,
            "total_length_m": cont.total_length_m,
        },
    }


def preview_contour(data: dict[str, Any]) -> dict[str, Any]:
    cfg, result = _pipeline_result(data)
    tc = result.thrust_chamber
    cont = result.contour
    return {
        "ok": True,
        "engine": cfg.engine,
        "summary": {
            "thrust_N": tc.thrust_N,
            "pc_bar": tc.pc_bar,
            "of_ratio": tc.of_ratio,
            "eps": tc.eps,
            "throat_radius_m": tc.throat_radius_m,
            "exit_radius_m": tc.exit_radius_m,
            "mdot_total_kg_s": tc.mdot_total_kg_s,
        },
        "contour": _contour_payload(cont),
        "warnings": list(result.warnings),
    }


def _synth_regen(cfg: EngineConfig) -> RegenConfig:
    """Build a preview-only regen layout from engine cooling scalars."""
    cool = cfg.cooling
    return RegenConfig(
        meta=MetaCfg(name=cfg.engine),
        contour=ContourCfg(type="from_engine"),
        channels=ChannelsCfg(
            count=cool.n_channels,
            inner_wall_thickness=cool.inner_wall_thickness_m,
            height=cool.channel_height_m,
            rib=RibCfg(mode="fixed_width", width=cool.rib_width_m),
        ),
        solver=SolverCfg(
            enabled=False,
            coolant=cool.coolant,
            inlet=CoolantInletCfg(
                pressure_bar=cool.inlet_p_bar,
                temperature_K=cool.inlet_T_K,
            ),
        ),
        sync=EngineSyncCfg(),
    )


def _build_layout(cfg: EngineConfig, result) -> ChannelLayout:
    regen = cfg.regen if cfg.regen is not None else _synth_regen(cfg)
    regen = prepare_regen_config(regen, result.thrust_chamber, result.combustion, cfg.chamber)
    contour = contour_from_resa(result.contour)
    return ChannelLayout(contour, regen)


def suggest_n_channels(data: dict[str, Any]) -> dict[str, Any]:
    cfg, result = _pipeline_result(data)
    rt = result.thrust_chamber.throat_radius_m
    cool = cfg.cooling
    circ = 2 * np.pi * (rt + cool.inner_wall_thickness_m)
    pitch = cool.channel_width_m + cool.rib_width_m
    n = max(4, int(circ / pitch))
    return {
        "n_channels": n,
        "throat_circumference_m": circ,
        "pitch_m": pitch,
        "throat_radius_m": rt,
    }


def preview_cooling_section(data: dict[str, Any], x_m: float | None = None) -> dict[str, Any]:
    cfg, result = _pipeline_result(data)
    lay = _build_layout(cfg, result)
    if x_m is None:
        x_m = float(lay.x_throat)
    x_m = float(np.clip(x_m, lay.x.min(), lay.x.max()))
    i = int(np.argmin(np.abs(lay.x - x_m)))
    regen = cfg.regen
    return {
        "ok": True,
        "x_m": float(lay.x[i]),
        "x_range": [float(lay.x.min()), float(lay.x.max())],
        "x_throat_m": float(lay.x_throat),
        "station": {
            "r_m": float(lay.r[i]),
            "r_ref_m": float(lay.r_ref[i]),
            "n_channels": lay.N,
            "channel_width_m": float(lay.w[i]),
            "channel_height_m": float(lay.h[i]),
            "rib_width_m": float(lay.t_rib[i]),
            "wall_thickness_m": float(lay.t_wall[i]),
            "beta_deg": float(np.degrees(lay.beta[i])),
            "pitch_perp_m": float(lay.pitch_perp[i]),
        },
        "profiles": {
            "x_m": lay.x.tolist(),
            "height_m": lay.h.tolist(),
            "rib_width_m": lay.t_rib.tolist(),
            "wall_thickness_m": lay.t_wall.tolist(),
            "channel_width_m": lay.w.tolist(),
            "beta_deg": np.degrees(lay.beta).tolist(),
        },
        "contour": _contour_payload(result.contour),
        "has_regen": regen is not None,
        "rib_mode": regen.channels.rib.mode if regen else "fixed_width",
    }


def preview_cooling_3d(data: dict[str, Any], channel_id: int = 0) -> dict[str, Any]:
    cfg, result = _pipeline_result(data)
    lay = _build_layout(cfg, result)
    if channel_id < 0 or channel_id >= lay.N:
        raise ValueError(f"channel_id must be 0..{lay.N - 1}")
    verts, faces, _ = build_channel_mesh(lay, [channel_id])
    th = np.linspace(0, 2 * np.pi, 48)
    xw = lay.x
    rw = lay.r
    wall_x = np.tile(xw[:, None], (1, len(th))).ravel()
    wall_y = (rw[:, None] * np.cos(th)[None, :]).ravel()
    wall_z = (rw[:, None] * np.sin(th)[None, :]).ravel()
    return {
        "ok": True,
        "channel_id": channel_id,
        "n_channels": lay.N,
        "vertices": verts.tolist(),
        "faces": faces.tolist(),
        "wall_vertices": np.column_stack([wall_x, wall_y, wall_z]).tolist(),
    }


def export_channel(
    data: dict[str, Any],
    channel_id: int = 0,
    fmt: Literal["stl", "step"] = "stl",
) -> Path:
    cfg, result = _pipeline_result(data)
    lay = _build_layout(cfg, result)
    if channel_id < 0 or channel_id >= lay.N:
        raise ValueError(f"channel_id must be 0..{lay.N - 1}")
    tag = cfg.engine.replace(" ", "_")
    ext = fmt
    path = Path(tempfile.gettempdir()) / f"{tag}_channel_{channel_id:02d}_mm.{ext}"
    if fmt == "stl":
        verts, faces, _ = build_channel_mesh(lay, [channel_id])
        write_binary_stl(str(path), verts, faces)
    else:
        write_step(str(path), lay, [channel_id])
    return path


def preview_regen_thermal(data: dict[str, Any]) -> dict[str, Any]:
    """Fast regen thermal solve for the design workspace (reduced station count)."""
    from resa.regen.integration import _build_contour
    from resa.regen_channels.solver import RegenSolver

    cfg, result = _pipeline_result(data)
    if cfg.regen is None:
        raise ValueError("Config has no regen block")
    regen = prepare_regen_config(
        cfg.regen, result.thrust_chamber, result.combustion, cfg.chamber,
    )
    if not regen.solver.enabled:
        return {
            "ok": True,
            "skipped": True,
            "reason": "Regen solver is disabled",
        }

    n_full = regen.geometry.n_stations
    n_preview = min(80, max(40, n_full // 3))
    if n_preview < n_full:
        regen = regen.model_copy(update={
            "geometry": regen.geometry.model_copy(update={"n_stations": n_preview}),
        })

    warnings: list[str] = []
    contour = _build_contour(regen, result.contour)
    lay = ChannelLayout(contour, regen)
    try:
        results = RegenSolver(lay, regen).solve()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    attrs = results.attrs
    if attrs.get("saturation_reached"):
        warnings.append("Bulk coolant reached saturation in part of the circuit")
    t_max = float(results.T_wall_hot_K.max())
    if t_max > regen.solver.wall.max_wall_temp_K:
        warnings.append(
            f"Hot wall exceeds {regen.solver.wall.max_wall_temp_K:.0f} K limit"
        )

    return {
        "ok": True,
        "preview_stations": n_preview,
        "full_stations": n_full,
        "summary": {
            "Q_total_kW": round(float(attrs["Q_total_kW"]), 2),
            "dp_bar": round(float(results.dp_cell_bar.sum()), 3),
            "outlet_T_K": round(float(attrs["outlet_T_K"]), 2),
            "outlet_p_bar": round(float(attrs["outlet_p_bar"]), 2),
            "T_wall_max_K": round(t_max, 1),
            "saturation_reached": bool(attrs.get("saturation_reached")),
        },
        "profiles": {
            "x_m": lay.x.tolist(),
            "T_wall_hot_K": results.T_wall_hot_K.tolist(),
            "p_cool_bar": results.p_cool_bar.tolist(),
            "q_w_W_m2": results.q_w_W_m2.tolist(),
            "v_m_s": results.v_m_s.tolist(),
        },
        "warnings": warnings,
    }


def format_validation_error(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
        for e in exc.errors()
    ]
