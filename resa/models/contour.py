"""Thrust chamber contour generation.

Builds the full wetted contour from injector face to nozzle exit, throat at x=0:

    injector ── cylinder ── entrance arc ── convergent cone ── [throat arcs] ── divergent
       x<0  ............................. 0 ............................. x>0

The cylinder→convergent junction carries a circular fillet (Sutton: R/Dc ≈ 0.25–0.75,
default 0.5 via ``rc_entrance_factor``).

Methods
-------
conical   : straight 15deg divergent cone (reference / simple cases)
rao_bell  : thrust-optimized parabola (quadratic Bezier between throat-arc
            tangent point and exit, using theta_n / theta_e)

Chamber length is derived from L* (= Vc/At): the convergent volume is computed
numerically and subtracted, the remainder sets the cylindrical length.

Angles: if theta_n_deg/theta_e_deg are not given in config, they are estimated
from a digitized Rao 80%-bell chart (see _estimate_rao_angles). Override in
config for non-80% bells or when MoC/CFD values are available.
"""
from __future__ import annotations

import numpy as np

from ..config.schema import ChamberConfig
from ..results import ContourResult, ThrustChamberResult
from .gasdynamics import mach_from_area_ratio

_DEG = np.pi / 180.0

# Digitized Rao thrust-optimized parabola angles for an 80% bell.
# Coarse but documented; override via config for fidelity / other bell %.
_RAO_EPS = np.array([3.0, 4.0, 5.0, 10.0, 15.0, 20.0, 30.0, 40.0, 50.0, 100.0])
_RAO_TN = np.array([26.5, 28.0, 30.0, 33.0, 34.0, 34.8, 36.0, 36.8, 37.2, 39.0])
_RAO_TE = np.array([18.5, 17.0, 16.0, 13.0, 11.8, 11.0, 10.0, 9.3, 9.0, 7.5])


def _estimate_rao_angles(eps: float) -> tuple[float, float]:
    """(theta_n, theta_e) in degrees, interpolated for an 80% bell."""
    tn = float(np.interp(eps, _RAO_EPS, _RAO_TN))
    te = float(np.interp(eps, _RAO_EPS, _RAO_TE))
    return tn, te


def _segment(x0, x1, r0, r1, n):
    """Linear segment helper (cylinder, cone)."""
    x = np.linspace(x0, x1, n)
    r = np.linspace(r0, r1, n)
    return x, r


def generate(
    tc: ThrustChamberResult, ch: ChamberConfig, gamma: float
) -> ContourResult:
    Rt = tc.throat_radius_m
    Re = tc.exit_radius_m
    eps = tc.eps
    Rc = np.sqrt(ch.contraction_ratio) * Rt          # chamber radius
    beta = ch.conv_half_angle_deg * _DEG             # convergent half-angle

    # throat arc radii
    R1 = ch.rt_upstream_factor * Rt                  # upstream (convergent) arc
    R2 = ch.rt_downstream_factor * Rt                # downstream (divergent) arc

    # --- divergent angles ---------------------------------------------------
    if ch.contour == "conical":
        # straight cone: entrance = exit = half-angle (theta_n overrides 15deg)
        alpha_deg = ch.theta_n_deg if ch.theta_n_deg is not None else 15.0
        theta_n = theta_e = alpha_deg
    else:
        tn_est, te_est = _estimate_rao_angles(eps)
        theta_n = ch.theta_n_deg if ch.theta_n_deg is not None else tn_est
        theta_e = ch.theta_e_deg if ch.theta_e_deg is not None else te_est
        if theta_n <= theta_e:
            raise ValueError(
                f"rao_bell needs theta_n > theta_e (got {theta_n:.1f}° <= "
                f"{theta_e:.1f}°) — the wall tangents would not intersect"
            )

    # ------------------------------------------------------------------ #
    # CONVERGENT SIDE (x <= 0)
    # ------------------------------------------------------------------ #
    # upstream throat arc: center (0, Rt+R1), phi 0..beta toward -x
    phi_up = np.linspace(0.0, beta, 60)
    x_arc_up = -R1 * np.sin(phi_up)
    r_arc_up = (Rt + R1) - R1 * np.cos(phi_up)
    xA1, rA1 = x_arc_up[-1], r_arc_up[-1]            # arc->cone tangent point

    # Sutton entrance fillet: R = (R/Dc) * Dc, tangent to cylinder and cone
    Rf = ch.rc_entrance_factor * 2.0 * Rc
    rB = Rc - Rf * (1.0 - np.cos(beta))              # fillet -> cone tangent
    dx_cone = (rB - rA1) / np.tan(beta)
    xB = xA1 - dx_cone
    xc = xB - Rf * np.sin(beta)                      # cylinder -> fillet tangent
    theta_f = np.linspace(0.0, beta, 40)
    x_fillet = xc + Rf * np.sin(theta_f)
    r_fillet = Rc - Rf * (1.0 - np.cos(theta_f))

    # convergent volume (throat back to xc): throat arc + cone + entrance fillet
    V_arc = np.trapezoid(np.pi * r_arc_up[::-1] ** 2, x_arc_up[::-1])
    V_frustum = np.pi * dx_cone / 3.0 * (rB**2 + rB * rA1 + rA1**2)
    V_fillet = np.trapezoid(
        np.pi * r_fillet**2 * (Rf * np.cos(theta_f)), theta_f
    )
    V_conv = V_arc + V_frustum + V_fillet

    # chamber cylinder length from L*
    Vc_total = ch.l_star_m * tc.throat_area_m2
    V_cyl = Vc_total - V_conv
    Ac = np.pi * Rc**2
    L_cyl = max(V_cyl / Ac, 0.0)
    x_inj = xc - L_cyl                              # injector face
    chamber_len = -x_inj                             # injector -> throat
    convergent_len = -xc                             # fillet+cone+arc (no cylinder)

    # ------------------------------------------------------------------ #
    # DIVERGENT SIDE (x >= 0)
    # ------------------------------------------------------------------ #
    # divergent arc ends tangent to the cone (conical) / bell entrance angle
    arc_end_angle = theta_n * _DEG
    alpha = theta_n * _DEG

    # downstream throat arc: phi 0..arc_end_angle
    phi_dn = np.linspace(0.0, arc_end_angle, 60)
    x_arc_dn = R2 * np.sin(phi_dn)
    r_arc_dn = (Rt + R2) - R2 * np.cos(phi_dn)
    xN, rN = x_arc_dn[-1], r_arc_dn[-1]              # divergent start (tangent)

    if ch.contour == "conical":
        # straight cone at angle alpha until r reaches Re
        L_div = xN + (Re - rN) / np.tan(alpha)
        x_div_extra, r_div_extra = _segment(xN, L_div, rN, Re, 80)
    else:
        # bell length: fraction of a 15deg conical of the same area ratio
        L_cone15 = (Re - Rt) / np.tan(15.0 * _DEG)
        L_div = ch.bell_fraction * L_cone15
        # quadratic Bezier: P0=N (slope tan tn), P2=E (slope tan te),
        # P1 = intersection of the two tangent lines.
        mN = np.tan(theta_n * _DEG)
        mE = np.tan(theta_e * _DEG)
        xE, rE = L_div, Re
        xP1 = (rE - rN - mE * xE + mN * xN) / (mN - mE)
        rP1 = rN + mN * (xP1 - xN)
        t = np.linspace(0.0, 1.0, 120)
        xb = (1 - t) ** 2 * xN + 2 * (1 - t) * t * xP1 + t**2 * xE
        rb = (1 - t) ** 2 * rN + 2 * (1 - t) * t * rP1 + t**2 * rE
        x_div_extra, r_div_extra = xb, rb

    # ------------------------------------------------------------------ #
    # ASSEMBLE full contour, throat at x=0
    # ------------------------------------------------------------------ #
    x_cyl, r_cyl = _segment(x_inj, xc, Rc, Rc, 30)
    x_cone, r_cone = _segment(xB, xA1, rB, rA1, 40)
    segs_x = [x_cyl, x_fillet, x_cone, x_arc_up[::-1], x_arc_dn, x_div_extra]
    segs_r = [r_cyl, r_fillet, r_cone, r_arc_up[::-1], r_arc_dn, r_div_extra]
    x = np.concatenate(segs_x)
    r = np.concatenate(segs_r)
    # dedupe near-identical x (segment joints)
    keep = np.concatenate([[True], np.abs(np.diff(x)) > 1e-12])
    x, r = x[keep], r[keep]

    area = np.pi * r**2
    eps_local = area / tc.throat_area_m2
    mach = np.array([
        1.0 if xi == 0 or abs(e - 1.0) < 1e-9
        else mach_from_area_ratio(e, gamma, supersonic=(xi > 0))
        for xi, e in zip(x, eps_local)
    ])

    return ContourResult(
        x_m=x, r_m=r, area_m2=area, mach=mach, method=ch.contour,
        chamber_radius_m=Rc, chamber_length_m=chamber_len,
        convergent_length_m=convergent_len, divergent_length_m=L_div,
        throat_radius_m=Rt, exit_radius_m=Re,
        contraction_ratio=ch.contraction_ratio, eps=eps,
        theta_n_deg=theta_n, theta_e_deg=theta_e,
        conv_entrance_radius_m=Rf,
    )
