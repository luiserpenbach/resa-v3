"""Correlations: friction (Churchill, rough), Gnielinski, Jackson
supercritical, Chen subcooled/nucleate boiling, helix curvature factors,
rib fin efficiency, Inconel 718 conductivity.
"""
from __future__ import annotations

import numpy as np
from CoolProp.CoolProp import PropsSI


# ---------------------------------------------------------------- friction
def churchill_f(Re: float, rel_rough: float) -> float:
    """Darcy friction factor, all regimes (Churchill 1977)."""
    Re = max(Re, 1.0)
    A = (2.457 * np.log(1.0 / ((7.0 / Re) ** 0.9 + 0.27 * rel_rough))) ** 16
    B = (37530.0 / Re) ** 16
    return 8.0 * ((8.0 / Re) ** 12 + 1.0 / (A + B) ** 1.5) ** (1.0 / 12.0)


def ito_curvature_friction(f_straight: float, Re: float, d_over_D: float):
    """Ito (1959) turbulent curved-pipe friction multiplier."""
    if d_over_D <= 0:
        return f_straight
    arg = Re * d_over_D ** 2
    if arg < 6.0:
        return f_straight
    return f_straight * (arg ** 0.05)


def curvature_htc_factor(Re: float, d_over_D: float) -> float:
    """Schmidt-type heat transfer enhancement in helical passages."""
    if d_over_D <= 0:
        return 1.0
    return 1.0 + 3.6 * (1.0 - d_over_D) * d_over_D ** 0.8


# ----------------------------------------------------------- single phase
def gnielinski(Re: float, Pr: float, f: float) -> float:
    """Nu for 3e3 < Re < 5e6 (clamped to laminar Nu=4.36 below)."""
    if Re < 2300.0:
        return 4.36
    fr = f / 8.0
    nu = fr * (Re - 1000.0) * Pr / (1.0 + 12.7 * np.sqrt(fr) * (Pr ** (2 / 3) - 1.0))
    return max(nu, 4.36)


# ----------------------------------------------------------- supercritical
def jackson_nu(Re: float, Pr: float, rho_w: float, rho_b: float,
               cp_bar: float, cp_b: float, T_b: float, T_w: float,
               T_pc: float) -> float:
    """Jackson & Hall supercritical correlation."""
    n = 0.4
    if T_b < T_pc < T_w:
        n = 0.4 + 0.2 * (T_w / T_pc - 1.0)
    elif T_pc <= T_b <= 1.2 * T_pc and T_b < T_w:
        n = 0.4 + 0.2 * (T_w / T_pc - 1.0) * (1.0 - 5.0 * (T_b / T_pc - 1.0))
    n = float(np.clip(n, 0.0, 1.0))
    return (0.0183 * Re ** 0.82 * Pr ** 0.5
            * (rho_w / rho_b) ** 0.3
            * max(cp_bar / cp_b, 1e-3) ** n)


# ----------------------------------------------------------------- boiling
def forster_zuber(coolant, p: float, T_w: float, T_sat: float) -> float:
    """Pool-boiling coefficient h_FZ [W/m2K] (Forster & Zuber 1955)."""
    dT = max(T_w - T_sat, 1e-3)
    p_w = PropsSI("P", "T", min(T_w, coolant.T_crit - 0.5), "Q", 0, coolant.cp_name) \
        if T_w < coolant.T_crit else coolant.p_crit
    dp = max(p_w - p, 1.0)
    rl = PropsSI("D", "P", p, "Q", 0, coolant.cp_name)
    rv = PropsSI("D", "P", p, "Q", 1, coolant.cp_name)
    cpl = PropsSI("C", "P", p, "Q", 0, coolant.cp_name)
    hfg = (PropsSI("H", "P", p, "Q", 1, coolant.cp_name)
           - PropsSI("H", "P", p, "Q", 0, coolant.cp_name))
    sig = PropsSI("SURFACE_TENSION", "P", p, "Q", 0, coolant.cp_name)
    mul, kl = coolant.transport(T_sat, rl)
    return (0.00122 * kl ** 0.79 * cpl ** 0.45 * rl ** 0.49
            / (sig ** 0.5 * mul ** 0.29 * hfg ** 0.24 * rv ** 0.24)
            * dT ** 0.24 * dp ** 0.75)


def chen_suppression(Re_l: float) -> float:
    return 1.0 / (1.0 + 2.53e-6 * Re_l ** 1.17)


# ------------------------------------------------------------------- walls
def fin_efficiency(h_c: float, k_wall: float, t_rib: float, height: float):
    """Adiabatic-tip rib fin efficiency."""
    m = np.sqrt(2.0 * h_c / max(k_wall * t_rib, 1e-12))
    mh = m * height
    return np.tanh(mh) / mh if mh > 1e-9 else 1.0


def k_inconel718(T: float) -> float:
    """Inconel 718 thermal conductivity [W/m/K], ~300-1300 K linear fit."""
    return float(np.clip(11.4 + 0.013 * (T - 300.0), 9.0, 26.0))
