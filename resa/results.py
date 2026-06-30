"""Result dataclasses. Frozen, typed, serializable.

PROVENANCE: ThrustChamberResult carries `provenance`, mapping key quantities to
how they were determined:
    "input"                      given in config
    "calculated"                 derived from other quantities
    "optimized: max Isp"         optimum found by the tool (O/F)
    "optimized: pe = p_amb"      optimum expansion chosen by the tool (eps)
Reports surface this next to every number, so a table always shows what was an
assumption vs a result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from .regen.integration import RegenResult


@dataclass(frozen=True)
class CombustionResult:
    cstar_ideal_m_s: float
    tc_K: float
    gamma: float
    mw_kg_kmol: float
    R_specific: float
    source: str                      # 'table' | 'rocketcea'


@dataclass(frozen=True)
class ThrustChamberResult:
    mode: str                        # 'design' | 'analyze'
    thrust_N: float
    pc_bar: float
    of_ratio: float
    mdot_total_kg_s: float
    mdot_ox_kg_s: float
    mdot_fuel_kg_s: float
    cstar_eff_m_s: float
    eta_cstar: float
    throat_area_m2: float
    throat_radius_m: float
    exit_area_m2: float
    exit_radius_m: float
    eps: float
    pe_bar: float
    cf: float
    isp_s: float
    exit_mach: float
    separated: bool                  # Summerfield pe < 0.4 p_amb
    eta_cf: float = 1.0              # nozzle (CF) efficiency applied
    pc_converged: bool = True        # analyze-mode Pc fixed-point convergence
    provenance: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ContourResult:
    x_m: np.ndarray
    r_m: np.ndarray
    area_m2: np.ndarray
    mach: np.ndarray
    method: str
    chamber_radius_m: float
    chamber_length_m: float
    convergent_length_m: float
    divergent_length_m: float
    throat_radius_m: float
    exit_radius_m: float
    contraction_ratio: float
    eps: float
    theta_n_deg: float
    theta_e_deg: float
    conv_entrance_radius_m: float = 0.0   # Sutton fillet at cylinder→convergent

    def __post_init__(self):
        n = len(self.x_m)
        assert len(self.r_m) == n == len(self.area_m2) == len(self.mach)

    @property
    def total_length_m(self) -> float:
        return self.chamber_length_m + self.divergent_length_m

    def station_table(self) -> np.ndarray:
        return np.column_stack([self.x_m, self.r_m, self.area_m2, self.mach])


# ---------------------------- off-design sweeps ---------------------------- #
@dataclass(frozen=True)
class SweepResult:
    """1-D sweep: parallel arrays of operating-point scalars."""
    kind: str                        # 'ox_throttle' | 'of_sweep'
    mdot_ox_kg_s: np.ndarray
    mdot_fuel_kg_s: np.ndarray
    mdot_total_kg_s: np.ndarray
    of: np.ndarray
    pc_bar: np.ndarray
    thrust_N: np.ndarray
    isp_s: np.ndarray
    cf: np.ndarray
    cstar_eff_m_s: np.ndarray
    pe_bar: np.ndarray
    separated: np.ndarray            # bool

    def table(self) -> np.ndarray:
        return np.column_stack([
            self.mdot_ox_kg_s, self.mdot_fuel_kg_s, self.mdot_total_kg_s,
            self.of, self.pc_bar, self.thrust_N, self.isp_s, self.cf,
            self.cstar_eff_m_s, self.pe_bar, self.separated.astype(int),
        ])

    HEADER = ("mdot_ox_kg_s,mdot_fuel_kg_s,mdot_total_kg_s,of,pc_bar,"
              "thrust_N,isp_s,cf,cstar_eff_m_s,pe_bar,separated")


@dataclass(frozen=True)
class EnvelopeResult:
    """2-D grid over (throttle fraction of total mdot) × O/F."""
    throttle_frac: np.ndarray        # (n_t,)
    of: np.ndarray                   # (n_of,)
    pc_bar: np.ndarray               # (n_of, n_t)
    thrust_N: np.ndarray
    isp_s: np.ndarray
    separated: np.ndarray            # bool grid


@dataclass(frozen=True)
class OffDesignResult:
    ox_throttle: Optional[SweepResult] = None
    of_sweep: Optional[SweepResult] = None
    envelope: Optional[EnvelopeResult] = None
    notes: tuple = ()


@dataclass(frozen=True)
class UncertaintyResult:
    """Bounding re-runs at eta_cstar ± tol (identical physics, pure re-run)."""
    eta_tol: float
    tc_lo: ThrustChamberResult          # eta - tol (pessimistic)
    tc_hi: ThrustChamberResult          # eta + tol (optimistic)
    od_lo: Optional[OffDesignResult] = None
    od_hi: Optional[OffDesignResult] = None


@dataclass(frozen=True)
class EngineResult:
    engine: str
    config_hash: str
    mode: str
    combustion: CombustionResult
    thrust_chamber: ThrustChamberResult
    contour: Optional[ContourResult] = None
    offdesign: Optional[OffDesignResult] = None
    uncertainty: Optional[UncertaintyResult] = None
    regen: Optional["RegenResult"] = None
    warnings: tuple = ()

    def summary(self) -> dict:
        tc = self.thrust_chamber
        p = tc.provenance
        d = {
            "engine": self.engine,
            "config_hash": self.config_hash,
            "mode": self.mode,
            "cstar_source": self.combustion.source,
            "thrust_N": round(tc.thrust_N, 1),
            "thrust_src": p.get("thrust", "?"),
            "pc_bar": round(tc.pc_bar, 3),
            "pc_src": p.get("pc", "?"),
            "of_ratio": round(tc.of_ratio, 3),
            "of_src": p.get("of_ratio", "?"),
            "eps": round(tc.eps, 3),
            "eps_src": p.get("eps", "?"),
            "mdot_kg_s": round(tc.mdot_total_kg_s, 4),
            "isp_s": round(tc.isp_s, 2),
            "cf": round(tc.cf, 4),
            "throat_r_mm": round(tc.throat_radius_m * 1e3, 3),
            "tc_K": round(self.combustion.tc_K, 1),
            "separated": tc.separated,
            "n_warnings": len(self.warnings),
        }
        if self.uncertainty is not None:
            u = self.uncertainty
            d["eta_tol"] = u.eta_tol
            d["isp_lo"] = round(u.tc_lo.isp_s, 2)
            d["isp_hi"] = round(u.tc_hi.isp_s, 2)
            d["pc_lo"] = round(u.tc_lo.pc_bar, 3)
            d["pc_hi"] = round(u.tc_hi.pc_bar, 3)
        if self.regen is not None:
            d.update({f"regen_{k}": v for k, v in self.regen.summary().items()})
        return d


def _clean_scalar(value):
    """JSON/YAML-safe scalar (arrays become lists)."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (np.floating, np.integer)):
        return float(value)
    if isinstance(value, dict):
        return {k: _clean_scalar(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_scalar(v) for v in value]
    return value


def sweep_to_dict(sweep: SweepResult) -> dict:
    """Serialize a 1-D sweep for API responses and results.yaml."""
    return _clean_scalar({
        "kind": sweep.kind,
        "mdot_ox_kg_s": sweep.mdot_ox_kg_s,
        "mdot_fuel_kg_s": sweep.mdot_fuel_kg_s,
        "mdot_total_kg_s": sweep.mdot_total_kg_s,
        "of": sweep.of,
        "pc_bar": sweep.pc_bar,
        "thrust_N": sweep.thrust_N,
        "isp_s": sweep.isp_s,
        "cf": sweep.cf,
        "cstar_eff_m_s": sweep.cstar_eff_m_s,
        "pe_bar": sweep.pe_bar,
        "separated": sweep.separated,
    })


def offdesign_to_dict(od: OffDesignResult) -> dict:
    """Serialize off-design sweeps (scalar arrays only, no contour data)."""
    payload: dict = {"notes": list(od.notes)}
    if od.ox_throttle is not None:
        payload["ox_throttle"] = sweep_to_dict(od.ox_throttle)
    if od.of_sweep is not None:
        payload["of_sweep"] = sweep_to_dict(od.of_sweep)
    if od.envelope is not None:
        env = od.envelope
        payload["envelope"] = _clean_scalar({
            "throttle_frac": env.throttle_frac,
            "of": env.of,
            "pc_bar": env.pc_bar,
            "thrust_N": env.thrust_N,
            "isp_s": env.isp_s,
            "separated": env.separated,
        })
    return payload
