"""Config schema. Single source of truth for what a valid engine definition is.

All units SI unless the field name says otherwise (``pc_bar``, ``thrust_N``).
Validation happens HERE, at load time — physics modules may assume valid input.

Two analysis modes (exactly one per config):
  operating_point  : DESIGN  — thrust + pc targets → geometry is computed
  analyze_point    : ANALYZE — measured geometry + mass flows → specs computed
                     (requires a `geometry:` block; hardware/test iteration mode)
"""
from __future__ import annotations

from typing import Literal, Optional, Union

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ..regen_channels.config import RegenConfig


class StrictModel(BaseModel):
    """Reject unknown YAML keys loudly (catches typos like `pc_barr`)."""
    model_config = dict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- #
# Propellants
# --------------------------------------------------------------------------- #
class PropellantConfig(StrictModel):
    name: str
    oxidizer: str                          # CoolProp name
    fuel: str                              # CoolProp name
    ox_temp_K: float = Field(gt=0)         # delivered ox temperature (tank/feed)
    fuel_temp_K: float = Field(gt=0)       # delivered fuel temperature
    cea_oxidizer: Optional[str] = None
    cea_fuel: Optional[str] = None


class CombustionTable(StrictModel):
    """CEA results, either a single point (scalars) or a 1-D table over O/F
    (equal-length lists). A table is REQUIRED for O/F optimization and sweeps.
    """
    of: Optional[list[float]] = None       # O/F grid (omit for single point)
    cstar_m_s: Union[float, list[float]]
    tc_K: Union[float, list[float]]
    gamma: Union[float, list[float]]
    mw_kg_kmol: Union[float, list[float]]

    @model_validator(mode="after")
    def _shapes(self) -> "CombustionTable":
        vals = [self.cstar_m_s, self.tc_K, self.gamma, self.mw_kg_kmol]
        is_list = [isinstance(v, list) for v in vals]
        if any(is_list):
            if not all(is_list) or self.of is None:
                raise ValueError("table: give `of` plus ALL properties as lists")
            n = len(self.of)
            if any(len(v) != n for v in vals):
                raise ValueError("table: all lists must match len(of)")
            if not np.all(np.diff(self.of) > 0):
                raise ValueError("table: `of` must be strictly increasing")
        return self

    @property
    def is_table(self) -> bool:
        return self.of is not None


class CombustionConfig(StrictModel):
    backend: Literal["rocketcea", "table"] = "table"
    table: Optional[CombustionTable] = None

    @model_validator(mode="after")
    def _table_required(self) -> "CombustionConfig":
        if self.backend == "table" and self.table is None:
            raise ValueError("combustion.backend='table' requires combustion.table")
        return self


# --------------------------------------------------------------------------- #
# DESIGN mode: operating point (targets)
# --------------------------------------------------------------------------- #
class OperatingPoint(StrictModel):
    thrust_N: float = Field(gt=0)
    pc_bar: float = Field(gt=0)
    eta_cstar: float = Field(gt=0.5, le=1.0)
    eta_cstar_tol: Optional[float] = Field(default=None, gt=0, lt=0.3)  # ± band
    # nozzle (thrust-coefficient) efficiency: divergence + boundary-layer losses
    eta_cf: float = Field(default=1.0, gt=0.5, le=1.0)
    p_amb_bar: float = Field(default=1.01325, ge=0)
    # optional — omitted -> optimum is computed (provenance records this)
    of_ratio: Optional[float] = Field(default=None, gt=0)   # None -> max-Isp O/F
    pe_bar: Optional[float] = Field(default=None, gt=0)     # design exit pressure
    eps: Optional[float] = Field(default=None, gt=1.0)      # ... or area ratio
    # if BOTH pe_bar and eps are None -> optimum expansion (pe = p_amb)

    @model_validator(mode="after")
    def _exit_condition(self) -> "OperatingPoint":
        if self.pe_bar is not None and self.eps is not None:
            raise ValueError("give at most one of pe_bar / eps")
        if self.pe_bar is not None and self.pe_bar >= self.pc_bar:
            raise ValueError("pe_bar must be < pc_bar")
        if self.p_amb_bar == 0 and self.pe_bar is None and self.eps is None:
            raise ValueError(
                "optimum expansion (pe = p_amb) is undefined in vacuum — "
                "give eps or pe_bar when p_amb_bar = 0"
            )
        if self.eta_cstar_tol and self.eta_cstar + self.eta_cstar_tol > 1.0:
            raise ValueError("eta_cstar + eta_cstar_tol must be <= 1.0")
        return self


# --------------------------------------------------------------------------- #
# ANALYZE mode: measured geometry + flows (hardware / test iteration)
# --------------------------------------------------------------------------- #
class GeometryConfig(StrictModel):
    throat_diameter_m: float = Field(gt=0)
    eps: Optional[float] = Field(default=None, gt=1.0)
    exit_diameter_m: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _exit(self) -> "GeometryConfig":
        if (self.eps is None) == (self.exit_diameter_m is None):
            raise ValueError("geometry: give exactly one of eps / exit_diameter_m")
        return self

    @property
    def throat_area_m2(self) -> float:
        return np.pi * (self.throat_diameter_m / 2.0) ** 2

    @property
    def area_ratio(self) -> float:
        if self.eps is not None:
            return self.eps
        return (self.exit_diameter_m / self.throat_diameter_m) ** 2


class AnalyzePoint(StrictModel):
    mdot_ox_kg_s: float = Field(gt=0)
    mdot_fuel_kg_s: float = Field(gt=0)
    eta_cstar: float = Field(gt=0.5, le=1.0)
    eta_cstar_tol: Optional[float] = Field(default=None, gt=0, lt=0.3)  # ± band
    # nozzle (thrust-coefficient) efficiency: divergence + boundary-layer losses
    eta_cf: float = Field(default=1.0, gt=0.5, le=1.0)
    p_amb_bar: float = Field(default=1.01325, ge=0)

    @model_validator(mode="after")
    def _tol(self) -> "AnalyzePoint":
        if self.eta_cstar_tol and self.eta_cstar + self.eta_cstar_tol > 1.0:
            raise ValueError("eta_cstar + eta_cstar_tol must be <= 1.0")
        return self


# --------------------------------------------------------------------------- #
# Off-design / throttle sweeps (run around the nominal point, fixed geometry)
# --------------------------------------------------------------------------- #
class OxThrottleSweep(StrictModel):
    """Vary ox flow, fuel constant (E2-style single-side throttling)."""
    ox_fraction: tuple[float, float] = (0.5, 1.15)   # × nominal mdot_ox
    n: int = Field(default=25, ge=5)


class OfSweep(StrictModel):
    """Vary O/F at constant TOTAL mass flow."""
    of_range: tuple[float, float]
    n: int = Field(default=30, ge=5)


class EnvelopeSweep(StrictModel):
    """2-D grid: total-flow throttle fraction × O/F."""
    throttle_fraction: tuple[float, float] = (0.6, 1.15)  # × nominal mdot_total
    of_range: tuple[float, float] = (3.5, 7.0)
    n: tuple[int, int] = (20, 20)                          # (throttle, of)


class OffDesignConfig(StrictModel):
    ox_throttle: Optional[OxThrottleSweep] = None
    of_sweep: Optional[OfSweep] = None
    envelope: Optional[EnvelopeSweep] = None


# --------------------------------------------------------------------------- #
# Chamber geometry (contour generation)
# --------------------------------------------------------------------------- #
class ChamberConfig(StrictModel):
    contraction_ratio: float = Field(gt=1.0)
    l_star_m: float = Field(gt=0)
    contour: Literal["rao_bell", "conical", "moc"] = "rao_bell"
    bell_fraction: float = Field(default=0.8, gt=0.5, le=1.0)
    conv_half_angle_deg: float = Field(default=40.0, gt=0, lt=60)
    rt_upstream_factor: float = Field(default=1.5, gt=0)
    rt_downstream_factor: float = Field(default=0.382, gt=0)
    # Sutton: entrance fillet radius R / chamber diameter Dc ∈ [0.25, 0.75]
    rc_entrance_factor: float = Field(default=0.5, gt=0, lt=1.5)
    bartz_correction: float = Field(default=0.75, gt=0, le=1.5)
    n_stations: int = Field(default=200, ge=20)
    theta_n_deg: Optional[float] = Field(default=None, gt=0, lt=60)
    theta_e_deg: Optional[float] = Field(default=None, ge=0, lt=30)


# --------------------------------------------------------------------------- #
# Cooling channels
# --------------------------------------------------------------------------- #
class CoolingConfig(StrictModel):
    coolant: str
    n_channels: int = Field(ge=4)
    channel_width_m: float = Field(gt=0)
    channel_height_m: float = Field(gt=0)
    rib_width_m: float = Field(gt=0)
    inner_wall_thickness_m: float = Field(gt=0)
    wall_material: str = "IN718"
    mdot_coolant_kg_s: Optional[float] = Field(default=None, gt=0)
    inlet_T_K: float = Field(gt=0)
    inlet_p_bar: float = Field(gt=0)
    correlation: Literal["gnielinski", "chen", "jackson"] = "gnielinski"


# --------------------------------------------------------------------------- #
# Top-level engine config
# --------------------------------------------------------------------------- #
class EngineConfig(StrictModel):
    engine: str
    description: str = ""                    # human-readable design note (studio / docs)
    propellants: PropellantConfig
    combustion: CombustionConfig
    chamber: ChamberConfig
    cooling: CoolingConfig
    operating_point: Optional[OperatingPoint] = None   # DESIGN mode
    analyze_point: Optional[AnalyzePoint] = None       # ANALYZE mode
    geometry: Optional[GeometryConfig] = None          # required for ANALYZE
    offdesign: Optional[OffDesignConfig] = None
    regen: Optional[RegenConfig] = None          # high-fidelity regen cooling
    config_hash: str = ""

    @model_validator(mode="after")
    def _mode(self) -> "EngineConfig":
        if (self.operating_point is None) == (self.analyze_point is None):
            raise ValueError(
                "give exactly one of operating_point (design) / "
                "analyze_point (analyze)"
            )
        if self.analyze_point is not None and self.geometry is None:
            raise ValueError("analyze_point requires a geometry block")
        c = self.cooling
        if c.n_channels * (c.channel_width_m + c.rib_width_m) > 1.0:
            raise ValueError("channel layout exceeds 1 m circumference — check units")
        return self

    @property
    def mode(self) -> str:
        return "design" if self.operating_point is not None else "analyze"
