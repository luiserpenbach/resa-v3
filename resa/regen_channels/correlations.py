"""Correlations: friction (Churchill, rough), Gnielinski / laminar rectangular
duct / Taylor (gaseous hydrogen), Jackson supercritical, Chen subcooled and
nucleate boiling, helix curvature factors, rib fin efficiency, Inconel 718
conductivity, and first-order wall stress formulas.
"""
from __future__ import annotations

import numpy as np
from CoolProp.CoolProp import PropsSI

RE_LAMINAR = 2300.0
RE_TURBULENT = 4000.0


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


def curvature_htc_factor(d_over_D: float) -> float:
    """Schmidt-type heat transfer enhancement in helical passages."""
    if d_over_D <= 0:
        return 1.0
    return 1.0 + 3.6 * (1.0 - d_over_D) * d_over_D ** 0.8


# ----------------------------------------------------------- single phase
# Shah & London (1978) fully developed laminar Nu, uniform heat flux (H1),
# rectangular duct, all four walls heated, vs short/long side ratio.
_RECT_ASPECT = np.array([0.0, 0.125, 0.25, 0.333, 0.5, 0.7, 1.0])
_RECT_NU_H1 = np.array([8.23, 6.49, 5.33, 4.79, 4.12, 3.73, 3.61])


def laminar_nu_rect(aspect: float) -> float:
    """Laminar Nu for a rectangular duct; aspect = short side / long side."""
    a = float(np.clip(aspect, 0.0, 1.0))
    return float(np.interp(a, _RECT_ASPECT, _RECT_NU_H1))


def gnielinski(Re: float, Pr: float, f: float) -> float:
    """Nu for 3e3 < Re < 5e6 (clamped to laminar circular-tube Nu=4.36 below)."""
    if Re < RE_LAMINAR:
        return 4.36
    fr = f / 8.0
    nu = fr * (Re - 1000.0) * Pr / (1.0 + 12.7 * np.sqrt(fr) * (Pr ** (2 / 3) - 1.0))
    return max(nu, 4.36)


def nu_single_phase(Re: float, Pr: float, f: float, aspect: float = 1.0) -> float:
    """Single-phase Nu with a laminar rectangular-duct floor and a linear
    blend across the transition band 2300 < Re < 4000."""
    nu_lam = laminar_nu_rect(aspect)
    if Re < RE_LAMINAR:
        return nu_lam
    if Re < RE_TURBULENT:
        w = (Re - RE_LAMINAR) / (RE_TURBULENT - RE_LAMINAR)
        return (1.0 - w) * nu_lam + w * max(gnielinski(RE_TURBULENT, Pr, f), nu_lam)
    return max(gnielinski(Re, Pr, f), nu_lam)


def taylor_nu(Re: float, Pr: float, T_w: float, T_b: float, x_over_D: float) -> float:
    """Taylor (NASA TN D-4332, 1968) correlation for gaseous hydrogen with
    strong wall-to-bulk temperature ratios:
        Nu_b = 0.023 Re_b^0.8 Pr_b^0.4 (T_w/T_b)^-(0.57 - 1.59 D/x)
    Bulk properties; x measured from the channel inlet."""
    xd = max(x_over_D, 2.0)
    expo = 0.57 - 1.59 / xd
    ratio = max(T_w / T_b, 1.0)
    return 0.023 * Re ** 0.8 * Pr ** 0.4 * ratio ** (-expo)


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


# ------------------------------------------------------------ wall stress
def thermal_stress_MPa(E_GPa: float, alpha_1_K: float, q_W_m2: float,
                       t_wall_m: float, k_W_mK: float, poisson: float) -> float:
    """Hot-wall compressive thermal stress from the through-wall gradient
    (Huzel & Huang eq. 4-27): sigma = E alpha q t / (2 (1 - nu) k)."""
    return E_GPa * 1e9 * alpha_1_K * q_W_m2 * t_wall_m / (2.0 * (1.0 - poisson) * k_W_mK) / 1e6


def pressure_bending_stress_MPa(dp_Pa: float, w_m: float, t_wall_m: float) -> float:
    """Bending stress in the hot wall spanning one channel under the
    coolant-minus-gas pressure difference, fixed-fixed beam
    (Huzel & Huang eq. 4-28): sigma = dp w^2 / (2 t^2)."""
    return dp_Pa * (w_m / t_wall_m) ** 2 / 2.0 / 1e6
