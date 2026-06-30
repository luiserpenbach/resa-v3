"""Thrust chamber: design sizing, reverse analysis, and the shared kernel.

Three public functions, one set of physics:

  evaluate_point(At, eps, mdot_ox, mdot_fuel, ...)  THE KERNEL
      fixed geometry + flows -> pc, thrust, isp, ... (one off-design point)
  size(op, model)                                   DESIGN mode
      thrust + pc targets -> geometry (+ optional O/F / eps optimization)
  analyze(geom, ap, model)                          ANALYZE mode
      measured geometry + flows -> specs (thin wrapper over the kernel)

Off-design sweeps (models/offdesign.py) map evaluate_point over ranges, so
reverse analysis and throttling are guaranteed to use identical physics.

Refs: Sutton, *Rocket Propulsion Elements*, 9th ed., ch. 3.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize_scalar

from ..config.schema import AnalyzePoint, GeometryConfig, OperatingPoint
from ..results import ThrustChamberResult
from .gasdynamics import (
    area_ratio_from_mach,
    mach_from_area_ratio,
    mach_from_pressure_ratio,
    pressure_ratio_from_mach,
)

_G0 = 9.80665
_BAR = 1.0e5
_SEP_LIMIT = 0.4          # Summerfield: separation risk if pe < ~0.4 p_amb


def _cf(pc: float, pe: float, pa: float, eps: float, g: float) -> float:
    """Thrust coefficient incl. ambient term (Sutton 3-30). Pressures in Pa."""
    term = (2.0 * g * g / (g - 1.0)) * (2.0 / (g + 1.0)) ** ((g + 1.0) / (g - 1.0))
    cf_mom = np.sqrt(term * (1.0 - (pe / pc) ** ((g - 1.0) / g)))
    return cf_mom + (pe - pa) / pc * eps


# --------------------------------------------------------------------------- #
# THE KERNEL: one operating point at fixed geometry
# --------------------------------------------------------------------------- #
def evaluate_point(
    at_m2: float,
    eps: float,
    mdot_ox: float,
    mdot_fuel: float,
    model,                      # CombustionModel
    eta_cstar: float,
    p_amb_bar: float,
    pc_guess_bar: float = 25.0,
    eta_cf: float = 1.0,
) -> dict:
    """Fixed geometry + mass flows -> resulting operating point (dict of scalars).

    pc converges by fixed-point iteration (instant for table backend, where c*
    has no pc dependence; a few iterations for rocketcea).
    """
    of = mdot_ox / mdot_fuel
    mdot = mdot_ox + mdot_fuel
    pc_bar = pc_guess_bar
    pc_converged = True
    for _ in range(20):
        comb = model.at(of, pc_bar=pc_bar)
        cstar_eff = comb.cstar_ideal_m_s * eta_cstar
        pc_new = mdot * cstar_eff / at_m2 / _BAR          # c* = pc·At/mdot
        converged = abs(pc_new - pc_bar) <= 1e-6 * pc_new
        pc_bar = pc_new
        if converged:
            break
    else:
        pc_converged = False
    # re-evaluate properties at the converged pc so gamma/Tc match pc_bar
    comb = model.at(of, pc_bar=pc_bar)
    cstar_eff = comb.cstar_ideal_m_s * eta_cstar

    g = comb.gamma
    pc = pc_bar * _BAR
    pa = p_amb_bar * _BAR
    Me = mach_from_area_ratio(eps, g, supersonic=True)
    pe = pc * pressure_ratio_from_mach(Me, g)
    cf = _cf(pc, pe, pa, eps, g) * eta_cf
    thrust = cf * pc * at_m2
    isp = thrust / (mdot * _G0)
    separated = bool(pa > 0 and pe < _SEP_LIMIT * pa)
    return dict(
        of=of, mdot=mdot, mdot_ox=mdot_ox, mdot_fuel=mdot_fuel,
        pc_bar=pc_bar, pe_bar=pe / _BAR, thrust_N=thrust, isp_s=isp,
        cf=cf, cstar_eff_m_s=cstar_eff, exit_mach=Me, gamma=g,
        separated=separated, comb=comb, pc_converged=pc_converged,
    )


# --------------------------------------------------------------------------- #
# DESIGN mode
# --------------------------------------------------------------------------- #
def _resolve_eps(op: OperatingPoint, g: float) -> tuple[float, float, float, str]:
    """-> (eps, Me, pe_Pa, provenance)."""
    pc = op.pc_bar * _BAR
    if op.eps is not None:
        eps, prov = op.eps, "input"
        Me = mach_from_area_ratio(eps, g, supersonic=True)
        pe = pc * pressure_ratio_from_mach(Me, g)
        return eps, Me, pe, prov
    if op.pe_bar is not None:
        pe, prov = op.pe_bar * _BAR, "calculated (from pe input)"
    else:  # optimum expansion: pe = p_amb (p_amb > 0 enforced by schema)
        pe, prov = op.p_amb_bar * _BAR, "optimized: pe = p_amb"
    # the exit must be supersonic: pe below the critical (choking) pressure
    p_crit = pc * (2.0 / (g + 1.0)) ** (g / (g - 1.0))
    if pe >= p_crit:
        raise ValueError(
            f"design exit pressure {pe/_BAR:.3f} bar is above the choking "
            f"limit {p_crit/_BAR:.3f} bar (gamma={g:.3f}) — the nozzle exit "
            "would be subsonic; lower pe_bar (or give eps directly)"
        )
    Me = mach_from_pressure_ratio(pc / pe, g)
    eps = area_ratio_from_mach(Me, g)
    return eps, Me, pe, prov


def _design_isp(of: float, op: OperatingPoint, model) -> float:
    comb = model.at(of, pc_bar=op.pc_bar)
    g = comb.gamma
    eps, Me, pe, _ = _resolve_eps(op, g)
    cf = _cf(op.pc_bar * _BAR, pe, op.p_amb_bar * _BAR, eps, g) * op.eta_cf
    return cf * comb.cstar_ideal_m_s * op.eta_cstar / _G0


def _resolve_of(op: OperatingPoint, model) -> tuple[float, str]:
    if op.of_ratio is not None:
        return op.of_ratio, "input"
    lo, hi = model.of_range      # raises clear error for single-point tables
    res = minimize_scalar(
        lambda of: -_design_isp(of, op, model),
        bounds=(lo, hi), method="bounded",
        options={"xatol": 1e-4},
    )
    return float(res.x), "optimized: max Isp"


def size(op: OperatingPoint, model) -> ThrustChamberResult:
    of, of_prov = _resolve_of(op, model)
    comb = model.at(of, pc_bar=op.pc_bar)
    g = comb.gamma
    pc = op.pc_bar * _BAR
    pa = op.p_amb_bar * _BAR

    eps, Me, pe, eps_prov = _resolve_eps(op, g)
    cf = _cf(pc, pe, pa, eps, g) * op.eta_cf

    cstar_eff = comb.cstar_ideal_m_s * op.eta_cstar
    at = op.thrust_N / (cf * pc)
    mdot = pc * at / cstar_eff
    mdot_ox = mdot * of / (1.0 + of)
    mdot_fuel = mdot / (1.0 + of)
    ae = at * eps

    return ThrustChamberResult(
        mode="design",
        thrust_N=op.thrust_N, pc_bar=op.pc_bar, of_ratio=of,
        mdot_total_kg_s=mdot, mdot_ox_kg_s=mdot_ox, mdot_fuel_kg_s=mdot_fuel,
        cstar_eff_m_s=cstar_eff, eta_cstar=op.eta_cstar, eta_cf=op.eta_cf,
        throat_area_m2=at, throat_radius_m=np.sqrt(at / np.pi),
        exit_area_m2=ae, exit_radius_m=np.sqrt(ae / np.pi),
        eps=eps, pe_bar=pe / _BAR, cf=cf,
        isp_s=cf * cstar_eff / _G0, exit_mach=Me,
        separated=bool(pa > 0 and pe < _SEP_LIMIT * pa),
        provenance={
            "thrust": "input", "pc": "input",
            "of_ratio": of_prov, "eps": eps_prov,
            "mdot": "calculated", "geometry": "calculated",
        },
    )


# --------------------------------------------------------------------------- #
# ANALYZE mode (reverse: measured hardware + flows -> specs)
# --------------------------------------------------------------------------- #
def analyze(geom: GeometryConfig, ap: AnalyzePoint, model) -> ThrustChamberResult:
    at = geom.throat_area_m2
    eps = geom.area_ratio
    pt = evaluate_point(
        at, eps, ap.mdot_ox_kg_s, ap.mdot_fuel_kg_s,
        model, ap.eta_cstar, ap.p_amb_bar, eta_cf=ap.eta_cf,
    )
    eps_prov = "input" if geom.eps is not None else "calculated (from exit dia)"
    return ThrustChamberResult(
        mode="analyze",
        thrust_N=pt["thrust_N"], pc_bar=pt["pc_bar"], of_ratio=pt["of"],
        mdot_total_kg_s=pt["mdot"], mdot_ox_kg_s=pt["mdot_ox"],
        mdot_fuel_kg_s=pt["mdot_fuel"],
        cstar_eff_m_s=pt["cstar_eff_m_s"], eta_cstar=ap.eta_cstar,
        eta_cf=ap.eta_cf,
        throat_area_m2=at, throat_radius_m=geom.throat_diameter_m / 2.0,
        exit_area_m2=at * eps, exit_radius_m=np.sqrt(at * eps / np.pi),
        eps=eps, pe_bar=pt["pe_bar"], cf=pt["cf"],
        isp_s=pt["isp_s"], exit_mach=pt["exit_mach"],
        separated=pt["separated"],
        pc_converged=pt["pc_converged"],
        provenance={
            "thrust": "calculated", "pc": "calculated",
            "of_ratio": "calculated (from mdots)", "eps": eps_prov,
            "mdot": "input", "geometry": "input",
        },
    )
