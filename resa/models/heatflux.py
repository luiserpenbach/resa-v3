"""Hot-gas heat-flux estimate along the chamber contour (hand-calc level).

Bartz film coefficient and adiabatic wall temperature from the same
``HotGas`` model the regen solver uses, evaluated at an ASSUMED uniform hot-wall
temperature — no channels, no wall conduction. Answers the early questions:

  * peak (throat) heat flux and where it sits
  * total heat load into the wall, chamber vs nozzle
  * can the fuel / oxidizer flow absorb that heat (bulk temperature rise)?

The regen solver replaces all of this once a channel layout exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..config.schema import EngineConfig
from ..regen_channels.config import HotGasCfg
from ..regen_channels.hotgas import HotGas
from ..results import EngineResult


@dataclass(frozen=True)
class CoolantCapacity:
    side: str                    # 'fuel' | 'oxidizer'
    fluid: str
    mdot_kg_s: float
    inlet_T_K: float
    pressure_bar: float
    outlet_T_K: Optional[float]  # bulk outlet if the whole flow absorbs Q
    dh_kJ_kg: float
    t_sat_K: Optional[float]     # at the pressure (None if supercritical)
    boils: bool
    note: str = ""


@dataclass(frozen=True)
class HeatFluxEstimate:
    wall_temp_K: float
    x_m: np.ndarray
    r_m: np.ndarray
    mach: np.ndarray
    t_aw_K: np.ndarray
    h_g_W_m2K: np.ndarray
    q_W_m2: np.ndarray
    q_lo_W_m2: Optional[np.ndarray]      # Bartz factor band (chamber.bartz_correction_tol)
    q_hi_W_m2: Optional[np.ndarray]
    q_max_W_m2: float
    x_q_max_m: float
    q_throat_W_m2: float
    Q_total_W: float
    Q_chamber_W: float                   # injector face -> throat
    Q_nozzle_W: float                    # throat -> exit
    wetted_area_m2: float
    property_note: str
    coolant: tuple = field(default=())   # CoolantCapacity per propellant side


def hot_gas_cfg(cfg: EngineConfig, res: EngineResult) -> HotGasCfg:
    """Hot-gas inputs synced from the engine result (as prepare_regen_config)."""
    tc, comb, ch = res.thrust_chamber, res.combustion, cfg.chamber
    kw = dict(
        pc_bar=tc.pc_bar, tc_K=comb.tc_K, gamma=comb.gamma,
        mol_mass_kg_kmol=comb.mw_kg_kmol, c_star_m_s=tc.cstar_eff_m_s,
        bartz_correction=ch.bartz_correction,
        throat_curvature_factor=0.5 * (ch.rt_upstream_factor + ch.rt_downstream_factor),
    )
    if (comb.has_transport and comb.cp_frozen_J_kgK is not None
            and min(comb.cp_frozen_J_kgK, comb.pr_frozen, comb.mu_Pa_s) > 0):
        kw.update(cp_J_kgK=comb.cp_frozen_J_kgK, pr=comb.pr_frozen, mu_pa_s=comb.mu_Pa_s)
    return HotGasCfg(**kw)


def _profile(hot: HotGas, x, r, x_t, T_w, cfg: EngineConfig, M=None):
    if M is None:
        M = hot.mach_profile(x, r, x_t)
    t_aw = hot.t_aw(M)
    fc = cfg.film_cooling
    if fc is not None:
        # same first-order relief as the regen solver (FilmCfg)
        x_inj = fc.injection_x_m if fc.injection_x_m is not None else float(x.min())
        eta = np.where(x >= x_inj, np.exp(-np.maximum(x - x_inj, 0.0)
                                          / fc.effectiveness_length_m), 0.0)
        t_aw = eta * fc.film_temp_K + (1.0 - eta) * t_aw
    eps_a = (r / r[np.argmin(r)]) ** 2
    hg = np.array([hot.h_g(m, e, T_w) for m, e in zip(M, eps_a)])
    return M, t_aw, hg, hg * np.maximum(t_aw - T_w, 0.0)


def _coolant_capacity(side: str, fluid: str, mdot: float, T_in: float, p_bar: float,
                      Q_W: float) -> CoolantCapacity:
    from CoolProp.CoolProp import PropsSI
    p = p_bar * 1e5
    dh = Q_W / mdot
    try:
        p_crit = PropsSI("PCRIT", fluid)
        t_sat = PropsSI("T", "P", p, "Q", 0, fluid) if p < p_crit else None
        h_in = PropsSI("H", "T", T_in, "P", p, fluid)
        try:
            T_out = PropsSI("T", "H", h_in + dh, "P", p, fluid)
        except ValueError:
            T_out = None
        boils = t_sat is not None and (T_out is None or T_out >= t_sat - 0.5) and T_in < t_sat
        note = ""
    except ValueError as exc:
        t_sat, T_out, boils, note = None, None, False, f"CoolProp: {exc}"
    return CoolantCapacity(side=side, fluid=fluid, mdot_kg_s=mdot, inlet_T_K=T_in,
                           pressure_bar=p_bar, outlet_T_K=T_out, dh_kJ_kg=dh / 1e3,
                           t_sat_K=t_sat, boils=bool(boils), note=note)


def estimate(cfg: EngineConfig, res: EngineResult, wall_temp_K: float = 800.0,
             coolant_pressure_bar: Optional[float] = None) -> HeatFluxEstimate:
    """Heat-flux profile at a uniform hot-wall temperature ``wall_temp_K``."""
    cont = res.contour
    if cont is None:
        raise ValueError("heat-flux estimate needs the chamber contour")
    i = np.argsort(cont.x_m)
    x, r = cont.x_m[i], cont.r_m[i]
    x_t = float(x[np.argmin(r)])
    rt = float(r.min())
    hcfg = hot_gas_cfg(cfg, res)
    At = np.pi * rt * rt
    r_curv = hcfg.throat_curvature_factor * rt
    hot = HotGas(hcfg, At, 2.0 * rt, r_curv)
    T_w = float(wall_temp_K)
    M, t_aw, hg, q = _profile(hot, x, r, x_t, T_w, cfg)

    q_lo = q_hi = None
    tol = cfg.chamber.bartz_correction_tol
    if tol:
        band = []
        for sgn in (-1.0, 1.0):
            hb = hcfg.model_copy(update={"bartz_correction": max(hcfg.bartz_correction + sgn * tol, 1e-3)})
            band.append(_profile(HotGas(hb, At, 2.0 * rt, r_curv), x, r, x_t, T_w, cfg, M)[3])
        q_lo, q_hi = band

    # wetted area element along the wall arc
    ds = np.sqrt(np.diff(x) ** 2 + np.diff(r) ** 2)
    rm = 0.5 * (r[1:] + r[:-1])
    qm = 0.5 * (q[1:] + q[:-1])
    dA = 2.0 * np.pi * rm * ds
    dQ = qm * dA
    xm = 0.5 * (x[1:] + x[:-1])
    Q_ch = float(dQ[xm <= x_t].sum())
    Q_nz = float(dQ[xm > x_t].sum())
    k = int(np.argmax(q))

    tc = res.thrust_chamber
    pr = cfg.propellants
    p_cool = coolant_pressure_bar or 1.5 * tc.pc_bar + 5.0
    coolant = []
    for side, fluid, mdot, T_in in (("fuel", pr.fuel, tc.mdot_fuel_kg_s, pr.fuel_temp_K),
                                    ("oxidizer", pr.oxidizer, tc.mdot_ox_kg_s, pr.ox_temp_K)):
        coolant.append(_coolant_capacity(side, fluid, mdot, T_in, p_cool, Q_ch + Q_nz))

    return HeatFluxEstimate(
        wall_temp_K=T_w, x_m=x, r_m=r, mach=M, t_aw_K=t_aw, h_g_W_m2K=hg, q_W_m2=q,
        q_lo_W_m2=q_lo, q_hi_W_m2=q_hi,
        q_max_W_m2=float(q[k]), x_q_max_m=float(x[k]),
        q_throat_W_m2=float(q[np.argmin(r)]),
        Q_total_W=Q_ch + Q_nz, Q_chamber_W=Q_ch, Q_nozzle_W=Q_nz,
        wetted_area_m2=float(dA.sum()), property_note=hot.property_note,
        coolant=tuple(coolant),
    )
