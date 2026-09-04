"""First-order nozzle loss estimate: throat Reynolds number, wall-shear
(boundary-layer) thrust loss and divergence efficiency.

Why: small thrusters (throat Re below ~1e5) lose several percent of CF to the
wall boundary layer, far more than the ~1 % of large engines, and a
hand-picked ``eta_cf`` hides that. This module gives a documented estimate
that the pipeline can either report next to the configured value or use in
place of it (``eta_cf_source: estimate``).

Method (deliberately simple, everything from the quasi-1D contour state):

* Local edge state at every contour station from the isentropic Mach
  distribution and the chamber gamma.
* Eckert reference temperature T* = T_e (1 + 0.032 M^2 + 0.58 (T_w/T_e - 1))
  with T_w = wall_temp_ratio * T_aw (cooled wall), viscosity mu ~ T^0.7 from the
  chamber value, density from the ideal gas law at T*.
* Flat-plate skin friction on the running length s from the injector face:
  laminar  c_f = 0.664 / sqrt(Re_s*)      (Re_s* < 5e5)
  turbulent c_f = 0.0592 Re_s*^-0.2
* Axial wall-shear drag  dF = tau_w cos(theta) 2 pi r ds, summed over the
  contour; loss fraction = dF / (CF_vac pc At).
* Divergence: lambda = (1 + cos theta)/2 with theta = exit angle for bells
  (Rao bells lose 0.5-1.5 %), the half-angle for cones.

  eta_cf_estimate = lambda * (1 - bl_loss_fraction)

Displacement-thickness effects on the effective area ratio are not included;
the estimate is a lower bound on the loss for very small nozzles.
"""
from __future__ import annotations

import numpy as np

from ..results import CombustionResult, ContourResult, NozzleLossEstimate, ThrustChamberResult
from .gasdynamics import pressure_ratio_from_mach, temperature_ratio_from_mach

_RE_TRANSITION = 5.0e5
_MU_DEFAULT = 9.0e-5        # Pa s, typical chamber value when no transport data
_MU_T_EXP = 0.7             # mu ~ T^0.7 (combustion gas mixtures)
RE_THROAT_WARN = 1.0e5


def throat_reynolds(mdot_kg_s: float, throat_radius_m: float, mu_Pa_s: float) -> float:
    """Re based on throat diameter and throat mass flux: 4 mdot / (pi D mu)."""
    return 4.0 * mdot_kg_s / (np.pi * 2.0 * throat_radius_m * mu_Pa_s)


def divergence_efficiency(method: str, theta_n_deg: float, theta_e_deg: float) -> float:
    ang = theta_n_deg if method == "conical" else theta_e_deg
    return 0.5 * (1.0 + np.cos(np.radians(ang)))


def estimate(
    cont: ContourResult,
    tc: ThrustChamberResult,
    comb: CombustionResult,
    *,
    wall_temp_ratio: float = 0.3,
    recovery: float = 0.9,
) -> NozzleLossEstimate:
    g, R, Tc = comb.gamma, comb.R_specific, comb.tc_K
    pc = tc.pc_bar * 1e5
    mu_c = comb.mu_Pa_s if comb.mu_Pa_s else _MU_DEFAULT
    method = "chamber viscosity from CEA" if comb.mu_Pa_s else "default chamber viscosity"

    i = np.argsort(cont.x_m)
    x, r, M = cont.x_m[i], cont.r_m[i], np.maximum(cont.mach[i], 1e-3)
    T = Tc * temperature_ratio_from_mach(M, g)
    p = pc * pressure_ratio_from_mach(M, g)
    u = M * np.sqrt(g * R * T)
    T_aw = T * (1.0 + recovery * 0.5 * (g - 1.0) * M * M)
    T_w = wall_temp_ratio * T_aw
    T_ref = T * (1.0 + 0.032 * M * M + 0.58 * (T_w / T - 1.0))
    T_ref = np.maximum(T_ref, 0.2 * T)
    rho_ref = p / (R * T_ref)
    mu_ref = mu_c * (T_ref / Tc) ** _MU_T_EXP

    dx = np.diff(x)
    dr = np.diff(r)
    ds = np.sqrt(dx * dx + dr * dr)
    s = np.concatenate([[0.0], np.cumsum(ds)])
    s_mid = 0.5 * (s[1:] + s[:-1])
    mid = lambda a: 0.5 * (a[1:] + a[:-1])
    re_s = np.maximum(mid(rho_ref) * mid(u) * np.maximum(s_mid, 1e-4) / mid(mu_ref), 10.0)
    laminar = re_s < _RE_TRANSITION
    cf_loc = np.where(laminar, 0.664 / np.sqrt(re_s), 0.0592 * re_s ** -0.2)
    tau = 0.5 * mid(rho_ref) * mid(u) ** 2 * cf_loc
    cos_theta = dx / np.maximum(ds, 1e-12)
    dF = tau * cos_theta * 2.0 * np.pi * mid(r) * ds
    drag = float(np.sum(dF))

    cf_vac_ideal = (tc.isp_vac_ideal_s * 9.80665 / comb.cstar_ideal_m_s
                    if tc.isp_vac_ideal_s else tc.cf / max(tc.eta_cf, 1e-9))
    f_vac_ideal = cf_vac_ideal * pc * tc.throat_area_m2
    bl_loss = drag / f_vac_ideal
    lam = divergence_efficiency(cont.method, cont.theta_n_deg, cont.theta_e_deg)
    mu_t = comb.mu_throat_Pa_s or mu_c * (temperature_ratio_from_mach(1.0, g)) ** _MU_T_EXP
    return NozzleLossEstimate(
        re_throat=float(throat_reynolds(tc.mdot_total_kg_s, tc.throat_radius_m, mu_t)),
        mu_throat_Pa_s=float(mu_t),
        bl_loss_fraction=float(bl_loss),
        laminar_fraction=float(np.sum(ds[laminar]) / np.sum(ds)),
        divergence_efficiency=float(lam),
        eta_cf_estimate=float(lam * (1.0 - bl_loss)),
        eta_cf_used=float(tc.eta_cf),
        method=f"flat-plate shear integral + divergence ({method})",
    )
