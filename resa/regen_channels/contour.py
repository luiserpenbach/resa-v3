"""Thrust chamber inner contour r(x).

Parametric mode builds the classic geometry: cylindrical chamber, blend arc
R1, conical convergent, throat arcs R2 (upstream) / Rd (downstream), then a
15-deg cone or a parabolic (quadratic Bezier) bell. Points mode interpolates
user data with PCHIP. x = 0 at the injector face, increasing downstream.
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator

from .config import ContourCfg, ParametricContourCfg


class Contour:
    def __init__(self, x: np.ndarray, r: np.ndarray):
        x = np.asarray(x, float)
        r = np.asarray(r, float)
        order = np.argsort(x)
        x, r = x[order], r[order]
        keep = np.concatenate(([True], np.diff(x) > 1e-12))
        self.x_raw, self.r_raw = x[keep], r[keep]
        self._itp = PchipInterpolator(self.x_raw, self.r_raw)
        self._der = self._itp.derivative()

    # -- basic queries ----------------------------------------------------
    @property
    def x_min(self): return float(self.x_raw[0])

    @property
    def x_max(self): return float(self.x_raw[-1])

    def r(self, x): return self._itp(np.clip(x, self.x_min, self.x_max))

    def drdx(self, x): return self._der(np.clip(x, self.x_min, self.x_max))

    def throat(self):
        """(x_t, r_t) at the minimum radius."""
        xs = np.linspace(self.x_min, self.x_max, 4001)
        rs = self.r(xs)
        i = int(np.argmin(rs))
        lo, hi = xs[max(i - 1, 0)], xs[min(i + 1, len(xs) - 1)]
        from scipy.optimize import minimize_scalar
        res = minimize_scalar(lambda q: float(self.r(q)),
                              bounds=(lo, hi), method="bounded")
        return float(res.x), float(res.fun)

    def area(self, x):
        return np.pi * self.r(x) ** 2


# ------------------------------------------------------------ parametric --
def _bell_bezier(p_start, theta_n, p_end, theta_e, n=120):
    """Quadratic Bezier bell: control point = intersection of end tangents."""
    x0, r0 = p_start
    x2, r2 = p_end
    m0, m2 = np.tan(theta_n), np.tan(theta_e)
    # intersection of r = r0 + m0 (x-x0) and r = r2 + m2 (x-x2)
    x1 = (r2 - r0 + m0 * x0 - m2 * x2) / (m0 - m2)
    r1 = r0 + m0 * (x1 - x0)
    t = np.linspace(0.0, 1.0, n)
    x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * x1 + t ** 2 * x2
    r = (1 - t) ** 2 * r0 + 2 * (1 - t) * t * r1 + t ** 2 * r2
    return x, r


def parametric_contour(p: ParametricContourCfg, pts_per_seg: int = 120):
    Rc, Rt = p.chamber_radius, p.throat_radius
    th_c = np.radians(p.contraction_angle_deg)
    R1, R2, Rd = p.r1_factor * Rc, p.r2_factor * Rt, p.rd_factor * Rt
    Re = Rt * np.sqrt(p.expansion_ratio)

    # build with throat at x = 0, shift later -----------------------------
    # upstream throat arc R2: centre (0, Rt + R2)
    phi = np.linspace(th_c, 0.0, pts_per_seg)
    x_a = -R2 * np.sin(phi)
    r_a = (Rt + R2) - R2 * np.cos(phi)
    xa0, ra0 = x_a[0], r_a[0]                  # cone-side end of arc

    # chamber blend arc R1: centre (xc, Rc - R1); ends slope 0 -> -tan(th_c)
    rb_end = Rc - R1 * (1.0 - np.cos(th_c))    # radius at cone-side end
    if rb_end <= ra0:
        raise ValueError("Contraction geometry infeasible: reduce arc radii "
                         "or contraction angle.")
    dx_cone = (rb_end - ra0) / np.tan(th_c)
    xb_end = xa0 - dx_cone
    xc_centre = xb_end - R1 * np.sin(th_c)
    phi1 = np.linspace(0.0, th_c, pts_per_seg)
    x_b = xc_centre + R1 * np.sin(phi1)
    r_b = (Rc - R1) + R1 * np.cos(phi1)

    # cylinder
    x_cyl_start = xc_centre - p.chamber_length
    x_cyl = np.linspace(x_cyl_start, xc_centre, pts_per_seg)
    r_cyl = np.full_like(x_cyl, Rc)

    # cone segment between arcs
    x_cone = np.linspace(xb_end, xa0, pts_per_seg)
    r_cone = rb_end - np.tan(th_c) * (x_cone - xb_end)

    # downstream throat arc Rd: centre (0, Rt + Rd)
    if p.nozzle_type == "cone":
        th_div = np.radians(p.cone_half_angle_deg)
        phi_d = np.linspace(0.0, th_div, pts_per_seg)
        x_d = Rd * np.sin(phi_d)
        r_d = (Rt + Rd) - Rd * np.cos(phi_d)
        x_div = np.linspace(x_d[-1], x_d[-1] + (Re - r_d[-1]) / np.tan(th_div),
                            pts_per_seg)
        r_div = r_d[-1] + np.tan(th_div) * (x_div - x_d[-1])
    else:  # bell
        th_n = np.radians(p.theta_n_deg)
        th_e = np.radians(p.theta_e_deg)
        phi_d = np.linspace(0.0, th_n, pts_per_seg)
        x_d = Rd * np.sin(phi_d)
        r_d = (Rt + Rd) - Rd * np.cos(phi_d)
        L_n = p.bell_fraction * (Re - Rt) / np.tan(np.radians(15.0))
        x_div, r_div = _bell_bezier((x_d[-1], r_d[-1]), th_n,
                                    (L_n, Re), th_e, n=pts_per_seg)

    x = np.concatenate([x_cyl, x_b, x_cone, x_a, x_d, x_div])
    r = np.concatenate([r_cyl, r_b, r_cone, r_a, r_d, r_div])
    x -= x[0]                                   # injector face at x = 0
    return x, r


def build_contour(cfg: ContourCfg) -> Contour:
    if cfg.type == "from_engine":
        raise ValueError(
            "contour.type=from_engine is resolved by RESA — pass a Contour "
            "from resa.regen.integration.contour_from_resa()"
        )
    if cfg.type == "parametric":
        x, r = parametric_contour(cfg.parametric)
    else:
        if cfg.points is not None:
            pts = np.asarray(cfg.points, float)
        else:
            pts = np.loadtxt(cfg.points_file, delimiter=",")
        x, r = pts[:, 0], pts[:, 1]
    return Contour(x, r)
