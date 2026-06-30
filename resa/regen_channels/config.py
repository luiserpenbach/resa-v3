"""Pydantic v2 schema for the regen channel YAML config (YAML-as-truth).

All lengths in the YAML are in **metres** unless the key name says otherwise
(`*_mm`, `*_bar`, `*_deg`). Profiles accept a scalar, [[x, v], ...] or
{points: ..., interp: pchip|linear}.
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

ProfileSpec = Union[float, List[List[float]], dict]


class MetaCfg(BaseModel):
    name: str = "unnamed"
    description: str = ""
    version: str = "0.1"


# ----------------------------------------------------------------- contour
class ParametricContourCfg(BaseModel):
    """Classic chamber + circular-arc throat + (cone | parabolic bell)."""
    chamber_radius: float
    chamber_length: float                       # cylindrical section length
    throat_radius: float
    contraction_angle_deg: float = 30.0
    r1_factor: float = 1.5    # chamber-side blend arc  R1 = r1_factor * Rc
    r2_factor: float = 1.5    # convergent throat arc   R2 = r2_factor * Rt
    rd_factor: float = 0.382  # divergent throat arc    Rd = rd_factor * Rt
    expansion_ratio: float = 4.0
    nozzle_type: Literal["cone", "bell"] = "bell"
    cone_half_angle_deg: float = 15.0
    bell_fraction: float = 0.8                  # length vs. 15 deg cone
    theta_n_deg: float = 21.0                   # bell initial angle
    theta_e_deg: float = 9.0                    # bell exit angle


class ContourCfg(BaseModel):
    type: Literal["parametric", "points", "from_engine"] = "parametric"
    parametric: Optional[ParametricContourCfg] = None
    points: Optional[List[List[float]]] = None  # [[x, r], ...] in metres
    points_file: Optional[str] = None           # CSV with x,r columns [m]

    @model_validator(mode="after")
    def _check(self):
        if self.type == "parametric" and self.parametric is None:
            raise ValueError("contour.type=parametric needs contour.parametric")
        if self.type == "points" and self.points is None and self.points_file is None:
            raise ValueError("contour.type=points needs points or points_file")
        if self.type == "from_engine" and (
            self.parametric is not None or self.points is not None
            or self.points_file is not None
        ):
            raise ValueError("contour.type=from_engine uses RESA engine contour only")
        return self


# ----------------------------------------------------------------- channels
class RibCfg(BaseModel):
    mode: Literal["fixed_width", "variable"] = "fixed_width"
    width: ProfileSpec = 1.0e-3   # scalar if fixed, profile if variable

    @model_validator(mode="after")
    def _check(self):
        if self.mode == "fixed_width" and not isinstance(self.width, (int, float)):
            raise ValueError("rib.mode=fixed_width requires a scalar rib.width")
        return self


class HelixCfg(BaseModel):
    """Helix angle beta measured from the AXIAL direction, in degrees.

    beta = 0  -> straight axial channel
    beta = const > 0 -> spiral with constant angle
    breakpoints -> start axial, switch to spiral, switch back, etc.
    """
    profile: ProfileSpec = 0.0
    interp: Literal["pchip", "linear"] = "pchip"
    handedness: Literal["right", "left"] = "right"


class ChannelsCfg(BaseModel):
    count: int = Field(gt=0)
    start_x: Optional[float] = None   # default: contour start (injector face)
    stop_x: Optional[float] = None    # default: contour end (nozzle exit)
    inner_wall_thickness: ProfileSpec = 0.8e-3
    height: ProfileSpec = 2.0e-3
    rib: RibCfg = RibCfg()
    helix: HelixCfg = HelixCfg()
    min_channel_width: float = 0.4e-3   # manufacturability guard (LPBF)


class GeometryCfg(BaseModel):
    n_stations: int = 300
    width_reference: Literal["mid_height", "floor"] = "mid_height"


# ----------------------------------------------------------------- solver
class HotGasCfg(BaseModel):
    """Replace defaults with CEA values for the real design point."""
    pc_bar: float = 25.0
    tc_K: float = 2950.0
    gamma: float = 1.22
    mol_mass_kg_kmol: float = 26.0
    mu_pa_s: float = 9.0e-5        # chamber-condition viscosity
    pr: Optional[float] = None     # default: 4*gamma / (9*gamma - 5)
    c_star_m_s: float = 1580.0
    bartz_correction: float = 0.75  # small-engine correction factor


class WallCfg(BaseModel):
    material: str = "Inconel 718"
    conductivity: Union[float, Literal["inconel718"]] = "inconel718"
    max_wall_temp_K: float = 1200.0   # flag threshold in reports


class CoolantInletCfg(BaseModel):
    pressure_bar: float
    temperature_K: float
    location: Literal["nozzle_end", "injector_end"] = "nozzle_end"


class SolverCfg(BaseModel):
    enabled: bool = True
    coolant: str = "NitrousOxide"
    hot_gas: HotGasCfg = HotGasCfg()
    wall: WallCfg = WallCfg()
    mdot_total: Optional[float] = None   # kg/s through ALL channels
    mdot_from_engine: bool = True        # legacy alias for sync.mdot
    of_ratio: float = 4.0
    coolant_side: Literal["oxidizer", "fuel"] = "oxidizer"
    coolant_fraction: Optional[float] = None  # override mdot = fraction * mdot_total
    inlet: CoolantInletCfg = CoolantInletCfg(pressure_bar=60.0,
                                             temperature_K=278.0)
    roughness: float = 8.0e-6            # LPBF as-built wall roughness [m]
    curvature_enhancement: bool = True   # helix curvature on HTC & friction
    max_iter_wall: int = 80


class ExportCfg(BaseModel):
    out_dir: str = "outputs"
    channel: Optional[int] = Field(default=None, ge=0)
    stl: bool = True
    stl_channels: Union[Literal["all"], int, List[int]] = "all"
    step: bool = False
    step_channels: Union[Literal["all"], int, List[int]] = "all"
    step_faceted: bool = False
    centerlines_csv: bool = True
    centerlines_channels: Union[Literal["all"], int, List[int]] = "all"
    geometry_csv: bool = True
    results_csv: bool = True
    html_3d: bool = True
    html_3d_channels: Union[Literal["all"], int, List[int]] = "all"
    html_plots: bool = True
    color_3d_by: str = "T_wall_hot"   # any results column, or "channel"

    def channel_ids(self, lay: "ChannelLayout", attr: str) -> list[int]:
        """Resolved channel list; ``export.channel`` overrides per-format specs."""
        from .mesh import resolve_channel_ids

        if self.channel is not None:
            return resolve_channel_ids(lay, self.channel)
        return resolve_channel_ids(lay, getattr(self, attr))


class EngineSyncCfg(BaseModel):
    """Opt-out of RESA auto-sync when regen runs through the engine pipeline.

    All default to ``true`` (sync from RESA). Set a flag to ``false`` to keep
    the value from the regen YAML instead.
    """
    contour: bool = True
    hot_gas_pc_bar: bool = True
    hot_gas_tc_K: bool = True
    hot_gas_gamma: bool = True
    hot_gas_mol_mass_kg_kmol: bool = True
    hot_gas_c_star_m_s: bool = True
    hot_gas_bartz_correction: bool = True
    of_ratio: bool = True
    mdot: bool = True


class RegenConfig(BaseModel):
    meta: MetaCfg = MetaCfg()
    contour: ContourCfg
    channels: ChannelsCfg
    geometry: GeometryCfg = GeometryCfg()
    solver: SolverCfg = SolverCfg()
    sync: EngineSyncCfg = EngineSyncCfg()
    export: ExportCfg = ExportCfg()

    @model_validator(mode="after")
    def _sync_compat(self) -> "RegenConfig":
        """Legacy ``solver.mdot_from_engine: false`` opts out of mdot sync."""
        if not self.solver.mdot_from_engine and self.sync.mdot:
            return self.model_copy(
                update={"sync": self.sync.model_copy(update={"mdot": False})})
        if self.contour.type == "from_engine" and not self.sync.contour:
            raise ValueError(
                "contour.type=from_engine requires sync.contour=true, or set "
                "contour.type to parametric/points with sync.contour=false"
            )
        if not self.sync.mdot and self.solver.mdot_total is None:
            raise ValueError(
                "sync.mdot=false requires solver.mdot_total in the regen YAML"
            )
        return self

    @classmethod
    def from_yaml(cls, path: str) -> "RegenConfig":
        import yaml
        with open(path) as f:
            raw: Any = yaml.safe_load(f)
        return cls.model_validate(raw)
