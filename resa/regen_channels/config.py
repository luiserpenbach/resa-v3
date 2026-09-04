"""Pydantic v2 schema for the regen channel YAML config (YAML-as-truth).

All lengths in the YAML are in **metres** unless the key name says otherwise
(`*_mm`, `*_bar`, `*_deg`). Profiles accept a scalar, [[x, v], ...] or
{points: ..., interp: pchip|linear}.
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel as _PydanticBaseModel
from pydantic import ConfigDict, Field, model_validator

ProfileSpec = Union[float, List[List[float]], dict]


class BaseModel(_PydanticBaseModel):
    """Strict base: unknown keys are rejected, matching the engine schema
    (a typo like ``heigth:`` must fail loudly, not fall back to defaults)."""

    model_config = ConfigDict(extra="forbid")


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
    """Replace defaults with CEA values for the real design point. When regen
    runs through the engine pipeline every field is synced from the engine
    result unless the matching ``sync`` flag is off."""
    pc_bar: float = 25.0
    tc_K: float = 2950.0
    gamma: float = 1.22
    mol_mass_kg_kmol: float = 26.0
    # transport properties for Bartz. None -> synced from the engine's
    # combustion model (CEA transport) when available, else the legacy
    # fallbacks (mu 9e-5 Pa s, Eucken Pr, cp = gamma R / (gamma - 1)) with a warning.
    mu_pa_s: Optional[float] = None
    pr: Optional[float] = None
    cp_J_kgK: Optional[float] = None
    # which CEA property set feeds Bartz: frozen (classic, conservative on Pr)
    # or equilibrium (includes recombination in cp/k; upper bound on h_g)
    property_basis: Literal["frozen", "equilibrium"] = "frozen"
    # throat-region c* for the mass flux pc / c* (effective c* when synced)
    c_star_m_s: float = 1580.0
    bartz_correction: float = 0.75  # small-engine correction factor
    # ± band on bartz_correction (regen solved at both ends -> T_wall band)
    bartz_correction_tol: Optional[float] = Field(default=None, gt=0, lt=1.0)
    # Bartz throat radius of curvature as a multiple of the throat RADIUS.
    # Default = mean of the 1.5 Rt upstream and 0.382 Rt downstream arcs.
    throat_curvature_factor: float = Field(default=0.941, gt=0)


class WallCfg(BaseModel):
    """Hot-wall material. ``material`` is looked up in
    ``regen_channels.materials`` (IN718, IN625, SS316L, CuCrZr, GRCop-42,
    C-103, copper). Explicit fields override the database."""
    material: str = "Inconel 718"
    # constant [W/m/K], the legacy 'inconel718' fit, or None -> material DB k(T)
    conductivity: Optional[Union[float, str]] = None
    # None -> material service limit from the database (1200 K if unknown)
    max_wall_temp_K: Optional[float] = None
    # structural overrides (None -> database); stress check needs all four
    yield_MPa: Optional[float] = None
    E_GPa: Optional[float] = None
    alpha_1_K: Optional[float] = None
    poisson: Optional[float] = None
    stress_check: bool = True
    # warn when (thermal + pressure) hot-wall stress / yield exceeds this; thin
    # regen walls normally yield at the throat (plastic, LCF-governed), so a
    # value > 1 lets you flag only the gross cases
    stress_ratio_warn: float = Field(default=1.0, gt=0)


class SkirtCfg(BaseModel):
    """Radiation-cooled nozzle extension downstream of ``channels.stop_x``:
    the wall settles where Bartz convection equals grey-body radiation to the
    environment. Conduction along the skirt is neglected."""
    enabled: bool = True
    emissivity: float = Field(default=0.8, gt=0, le=1.0)
    T_env_K: float = Field(default=300.0, ge=0)   # 4 K deep space, ~300 K test cell
    material: Optional[str] = None                # for the temperature limit
    max_wall_temp_K: Optional[float] = None       # overrides the material limit


class CoolantInletCfg(BaseModel):
    pressure_bar: float
    temperature_K: float
    location: Literal["nozzle_end", "injector_end"] = "nozzle_end"


class FilmCfg(BaseModel):
    """First-order film wall relief: T_aw_eff = eta*T_film + (1-eta)*T_aw
    with eta(x) = exp(-(x - x_inj)/L) downstream of the injection station."""
    injection_x_m: Optional[float] = None      # default: channel start (min x)
    effectiveness_length_m: float = Field(gt=0)
    film_temp_K: float = Field(default=600.0, gt=0)


class SolverCfg(BaseModel):
    enabled: bool = True
    coolant: str = "NitrousOxide"
    hot_gas: HotGasCfg = HotGasCfg()
    wall: WallCfg = WallCfg()
    mdot_total: Optional[float] = None   # kg/s through ALL channels
    mdot_from_engine: bool = True        # legacy alias for sync.mdot
    of_ratio: float = 4.0
    # which propellant flow cools the chamber. None -> inferred from the
    # coolant species vs the engine propellants (must match one of them);
    # standalone runs without mdot_total must set it explicitly.
    coolant_side: Optional[Literal["oxidizer", "fuel"]] = None
    coolant_fraction: Optional[float] = None  # override mdot = fraction * mdot_total
    inlet: CoolantInletCfg = CoolantInletCfg(pressure_bar=60.0,
                                             temperature_K=278.0)
    roughness: float = 8.0e-6            # LPBF as-built wall roughness [m]
    curvature_enhancement: bool = True   # helix curvature on HTC & friction
    # auto: Gnielinski (laminar rectangular-duct floor, transition blend) with
    #       Jackson at supercritical pressure and Chen when boiling
    # taylor: NASA gaseous-hydrogen correlation (wall/bulk temperature ratio)
    coolant_correlation: Literal["auto", "gnielinski", "taylor"] = "auto"
    max_coolant_mach: float = Field(default=0.3, gt=0)   # warning threshold
    # feed-pressure budget: outlet pressure must cover pc (1 + fraction)
    injector_dp_fraction: float = Field(default=0.2, ge=0)
    max_iter_wall: int = 200             # brentq iterations per wall solve
    film: Optional[FilmCfg] = None       # synced from engine film_cooling
    skirt: SkirtCfg = SkirtCfg()         # uncooled extension past stop_x


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
    hot_gas_c_star_m_s: bool = True          # effective c* (pc / c*_eff = throat mass flux)
    hot_gas_bartz_correction: bool = True    # incl. bartz_correction_tol
    hot_gas_transport: bool = True           # cp, mu, Pr from CEA (property_basis)
    hot_gas_throat_curvature: bool = True    # from chamber rt_*_factor arcs
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
        out = self
        if not out.solver.mdot_from_engine and out.sync.mdot:
            # Normalize first (model_copy does not re-validate), then run the
            # remaining checks against the normalized state — an early return
            # here used to skip them entirely.
            out = out.model_copy(
                update={"sync": out.sync.model_copy(update={"mdot": False})})
        if out.contour.type == "from_engine" and not out.sync.contour:
            raise ValueError(
                "contour.type=from_engine requires sync.contour=true, or set "
                "contour.type to parametric/points with sync.contour=false"
            )
        if not out.sync.mdot and out.solver.mdot_total is None:
            raise ValueError(
                "sync.mdot=false requires solver.mdot_total in the regen YAML"
            )
        return out

    @classmethod
    def from_yaml(cls, path: str) -> "RegenConfig":
        import yaml
        with open(path) as f:
            raw: Any = yaml.safe_load(f)
        return cls.model_validate(raw)
