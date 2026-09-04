"""Result dataclasses. Frozen, typed, serializable.

PROVENANCE: ThrustChamberResult carries `provenance`, mapping key quantities to
how they were determined:
    "input"                      given in config
    "calculated"                 derived from other quantities
    "optimized: max Isp"         optimum found by the tool (O/F)
    "optimized: pe = p_amb"      optimum expansion chosen by the tool (eps)
    "estimated: ..."             first-order model estimate (e.g. eta_cf)
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
    gamma: float                     # chamber isentropic exponent (equilibrium for CEA)
    mw_kg_kmol: float
    R_specific: float
    source: str                      # 'table' | 'rocketcea'
    # chamber transport properties (None when the backend cannot supply them)
    cp_frozen_J_kgK: Optional[float] = None
    mu_Pa_s: Optional[float] = None
    k_frozen_W_mK: Optional[float] = None
    pr_frozen: Optional[float] = None
    cp_eq_J_kgK: Optional[float] = None
    k_eq_W_mK: Optional[float] = None
    pr_eq: Optional[float] = None
    mu_throat_Pa_s: Optional[float] = None
    # propellant reference states actually used by the combustion backend
    ox_state: str = ""               # e.g. 'O2(L) at 90.2 K (CEA default)'
    fuel_state: str = ""
    nozzle_flow: str = "single_gamma"

    @property
    def has_transport(self) -> bool:
        return self.mu_Pa_s is not None and self.pr_frozen is not None


@dataclass(frozen=True)
class NozzleState:
    """Ideal nozzle expansion state for one (O/F, pc, eps)."""
    cf_vac: float                    # ideal vacuum thrust coefficient
    pe_over_pc: float
    exit_mach: float
    gamma_exit: float
    source: str                      # 'single_gamma' | 'cea_equilibrium' | 'cea_frozen' | ...


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
    cf_source: str = "single_gamma"  # how the ideal CF was obtained
    isp_vac_ideal_s: Optional[float] = None   # ideal vacuum Isp (no efficiencies)
    gamma_exit: Optional[float] = None
    provenance: dict = field(default_factory=dict)


@dataclass(frozen=True)
class NozzleReference:
    """Ideal vacuum Isp of the nominal point under every nozzle-flow model the
    backend can evaluate (rocketcea only). Shows the equilibrium/frozen band
    around whichever model the config selected."""
    selected: str
    eps: float
    isp_vac_single_gamma_s: float
    isp_vac_equilibrium_s: Optional[float] = None
    isp_vac_frozen_s: Optional[float] = None
    isp_vac_frozen_at_throat_s: Optional[float] = None

    def spread_fraction(self) -> Optional[float]:
        """(equilibrium - frozen) / equilibrium, or None."""
        if self.isp_vac_equilibrium_s is None or self.isp_vac_frozen_s is None:
            return None
        return (self.isp_vac_equilibrium_s - self.isp_vac_frozen_s) / self.isp_vac_equilibrium_s


@dataclass(frozen=True)
class NozzleLossEstimate:
    """First-order nozzle loss estimate (see models/losses.py)."""
    re_throat: float
    mu_throat_Pa_s: float
    bl_loss_fraction: float          # wall-shear thrust loss / ideal vacuum thrust
    laminar_fraction: float          # fraction of wetted length with laminar BL
    divergence_efficiency: float     # lambda
    eta_cf_estimate: float           # lambda * (1 - bl_loss_fraction)
    eta_cf_used: float
    method: str


@dataclass(frozen=True)
class CouplingResult:
    """Outcome of the iterative loops in the pipeline (regen outlet -> propellant
    temperature, estimated eta_cf -> sizing)."""
    iterations: int
    converged: bool
    fuel_temp_K: float
    ox_temp_K: float
    regen_outlet_T_K: Optional[float] = None
    coupled_side: Optional[str] = None
    eta_cf: Optional[float] = None
    history: tuple = ()


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
        if not (len(self.r_m) == n == len(self.area_m2) == len(self.mach)):
            raise ValueError("contour arrays must have equal length")

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
class FilmCoolingResult:
    """First-order film cooling bookkeeping (see resa/models/film.py)."""
    fraction: float
    side: str
    of_overall: float
    of_core: float
    mdot_film_kg_s: float
    mdot_total_kg_s: float          # tank-side total incl. film
    isp_core_s: float
    isp_delivered_s: float          # thrust / (total mdot * g0)

    def summary(self) -> dict:
        return {
            "fraction": self.fraction,
            "side": self.side,
            "of_overall": self.of_overall,
            "of_core": self.of_core,
            "mdot_film_kg_s": self.mdot_film_kg_s,
            "mdot_total_kg_s": self.mdot_total_kg_s,
            "isp_delivered_s": self.isp_delivered_s,
        }


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
    film: Optional[FilmCoolingResult] = None
    nozzle_reference: Optional[NozzleReference] = None
    losses: Optional[NozzleLossEstimate] = None
    coupling: Optional[CouplingResult] = None
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
            "cf_src": tc.cf_source,
            "eta_cf": round(tc.eta_cf, 4),
            "throat_r_mm": round(tc.throat_radius_m * 1e3, 3),
            "tc_K": round(self.combustion.tc_K, 1),
            "separated": tc.separated,
            "n_warnings": len(self.warnings),
        }
        if self.nozzle_reference is not None:
            r = self.nozzle_reference
            if r.isp_vac_equilibrium_s is not None:
                d["isp_vac_eq_ideal_s"] = round(r.isp_vac_equilibrium_s, 2)
            if r.isp_vac_frozen_s is not None:
                d["isp_vac_frozen_ideal_s"] = round(r.isp_vac_frozen_s, 2)
        if self.losses is not None:
            d["re_throat"] = round(self.losses.re_throat, 0)
            d["eta_cf_est"] = round(self.losses.eta_cf_estimate, 4)
        if self.coupling is not None:
            d["fuel_temp_K"] = round(self.coupling.fuel_temp_K, 1)
            d["ox_temp_K"] = round(self.coupling.ox_temp_K, 1)
        if self.uncertainty is not None:
            u = self.uncertainty
            d["eta_tol"] = u.eta_tol
            d["isp_lo"] = round(u.tc_lo.isp_s, 2)
            d["isp_hi"] = round(u.tc_hi.isp_s, 2)
            d["pc_lo"] = round(u.tc_lo.pc_bar, 3)
            d["pc_hi"] = round(u.tc_hi.pc_bar, 3)
        if self.film is not None:
            d.update({f"film_{k}": v for k, v in self.film.summary().items()})
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
