"""1D enthalpy-marching finite-volume regen solver with regime switching.

Per cell, marching along the coolant flow direction:
  1. Bulk state from (p, h) via CoolProp.
  2. Coolant HTC: Gnielinski baseline with a laminar rectangular-duct floor
     and a transition blend; Jackson supercritical correction at p > p_crit;
     Chen-style superposition (suppressed Forster-Zuber + forced convection)
     when the cold wall exceeds T_sat at subcritical pressure; or the Taylor
     gaseous-hydrogen correlation (``coolant_correlation: taylor``).
     Helix curvature enhances both HTC (Schmidt) and friction (Ito).
  3. Wall energy balance solved per station with brentq on T_wall_hot:
         q'' = h_g(T_wh) * (T_aw - T_wh)                 [Bartz, sigma(T_wh)]
         T_wc = T_wh - q'' * t_wall / k_wall(T)
         q'' * dA_hot = h_c(T_wc) * (w + 2*eta_fin*h) * dl * (T_wc - T_b)
     A failed bracket falls back to a bracket end AND is counted
     (``attrs['wall_solve_fallbacks']``) so it can never pass silently.
  4. Update h (energy) and p (friction + acceleration + curvature).
  5. First-order wall stress (Huzel & Huang): through-wall thermal stress +
     pressure bending across the channel span vs. yield at the hot-face
     temperature, when the material is known.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from . import correlations as co
from . import materials
from .coolant import Coolant
from .hotgas import HotGas
from .layout import ChannelLayout

log = logging.getLogger(__name__)


def _resolve_wall(wall_cfg):
    """-> (material or None, k(T) callable, k source, limit K, limit source,
    stress props or None)."""
    mat = materials.resolve(wall_cfg.material)
    cond = wall_cfg.conductivity
    if cond is None:
        if mat is None:
            raise ValueError(
                f"regen: wall material {wall_cfg.material!r} is not in the material "
                "database — give solver.wall.conductivity [W/m/K] (and yield_MPa, "
                "E_GPa, alpha_1_K, poisson for the stress check)")
        k_fn, k_src = mat.k, f"{mat.name} k(T) table"
    elif isinstance(cond, str):
        m2 = materials.resolve(cond)
        if m2 is None:
            raise ValueError(f"regen: unknown conductivity keyword {cond!r}")
        k_fn, k_src = m2.k, f"{m2.name} k(T) table"
    else:
        val = float(cond)
        k_fn, k_src = (lambda T, v=val: v), f"constant {val:g} W/m/K"
    if wall_cfg.max_wall_temp_K is not None:
        limit, limit_src = float(wall_cfg.max_wall_temp_K), "config"
    elif mat is not None:
        limit, limit_src = mat.max_service_T_K, f"{mat.name} service limit"
    else:
        limit, limit_src = 1200.0, "default (unknown material)"
    E = wall_cfg.E_GPa if wall_cfg.E_GPa is not None else (mat.E_GPa if mat else None)
    alpha = wall_cfg.alpha_1_K if wall_cfg.alpha_1_K is not None else (mat.alpha_1_K if mat else None)
    nu = wall_cfg.poisson if wall_cfg.poisson is not None else (mat.poisson if mat else None)
    if wall_cfg.yield_MPa is not None:
        yfn = (lambda T, v=float(wall_cfg.yield_MPa): v)
    elif mat is not None:
        yfn = mat.yield_MPa
    else:
        yfn = None
    stress = None
    if wall_cfg.stress_check and None not in (E, alpha, nu) and yfn is not None:
        stress = (float(E), float(alpha), float(nu), yfn)
    return mat, k_fn, k_src, limit, limit_src, stress


class RegenSolver:
    def __init__(self, layout: ChannelLayout, cfg):
        self.lay = layout
        self.cfg = cfg.solver
        self.coolant = Coolant(self.cfg.coolant)

        # hot-gas model anchored at the full-contour throat
        Dt = 2.0 * layout.r_throat
        r_curv = self.cfg.hot_gas.throat_curvature_factor * layout.r_throat
        self.hot = HotGas(self.cfg.hot_gas, layout.A_throat, Dt, r_curv)

        (self.material, self.k_wall, self.k_source, self.wall_limit,
         self.wall_limit_source, self.stress_props) = _resolve_wall(self.cfg.wall)

        # coolant mass flow
        self.coolant_side = self.cfg.coolant_side
        if self.cfg.mdot_total is not None:
            self.mdot_total = self.cfg.mdot_total
        elif self.cfg.mdot_from_engine:
            if self.cfg.coolant_fraction is not None:
                frac = self.cfg.coolant_fraction
            elif self.coolant_side is None:
                raise ValueError(
                    "regen: solver.coolant_side is not set and cannot be inferred "
                    "(standalone run) — set coolant_side: fuel|oxidizer or "
                    "solver.mdot_total")
            elif self.coolant_side == "fuel":
                frac = 1.0 / (1.0 + self.cfg.of_ratio)
            else:
                frac = self.cfg.of_ratio / (1.0 + self.cfg.of_ratio)
            self.mdot_total = self.hot.mdot * frac
        else:
            raise ValueError("Set solver.mdot_total or mdot_from_engine")
        self.mdot_ch = self.mdot_total / layout.N
        self.wall_solve_fallbacks = 0

        corr = self.cfg.coolant_correlation
        if corr == "auto":
            corr = "gnielinski"
        self.correlation = corr

    # ----------------------------------------------------------------- HTC
    def _h_c(self, st, T_wc: float, G: float, Dh: float, d_over_D: float,
             rel_rough: float, aspect: float, x_over_D: float):
        """Coolant heat transfer coefficient at given cold-wall temperature.
        Returns (h_c, Re, f_darcy, regime)."""
        Re = G * Dh / st.mu
        f = co.churchill_f(Re, rel_rough)
        if self.cfg.curvature_enhancement:
            f = co.ito_curvature_friction(f, Re, d_over_D)
        cool = self.coolant

        if self.correlation == "taylor":
            Nu = co.taylor_nu(Re, st.Pr, T_wc, st.T, x_over_D)
            if Re < co.RE_TURBULENT:
                Nu = max(Nu, co.nu_single_phase(Re, st.Pr, f, aspect))
            h_conv = Nu * st.k / Dh
            if self.cfg.curvature_enhancement:
                h_conv *= co.curvature_htc_factor(d_over_D)
            regime = "taylor_gas" if Re >= co.RE_LAMINAR else "laminar"
            return h_conv, Re, f, regime

        Nu = co.nu_single_phase(Re, st.Pr, f, aspect)
        regime = "single_phase" if Re >= co.RE_TURBULENT else (
            "transitional" if Re >= co.RE_LAMINAR else "laminar")

        if st.is_supercritical_p:
            if Re >= co.RE_TURBULENT:
                try:
                    T_pc = cool.T_crit * float(np.clip(
                        1.0 + 0.6 * (st.p / cool.p_crit - 1.0), 1.0, 1.4))
                    rho_w, h_w, mu_w, k_w, cp_w = cool.wall_props(st.p, T_wc)
                    cp_bar = ((h_w - st.h) / (T_wc - st.T)
                              if T_wc > st.T + 0.1 else st.cp)
                    Nu_j = co.jackson_nu(Re, st.Pr, rho_w, st.rho, cp_bar, st.cp,
                                         st.T, T_wc, T_pc)
                    if Nu_j > 0:
                        Nu = Nu_j
                        regime = "supercritical"
                except Exception as exc:
                    log.debug("Jackson supercritical HTC skipped: %s", exc)
            h_conv = Nu * st.k / Dh
            if self.cfg.curvature_enhancement:
                h_conv *= co.curvature_htc_factor(d_over_D)
            return h_conv, Re, f, regime

        h_conv = Nu * st.k / Dh
        if self.cfg.curvature_enhancement:
            h_conv *= co.curvature_htc_factor(d_over_D)

        if not np.isnan(st.T_sat) and T_wc > st.T_sat + 0.05:
            # subcooled / saturated nucleate boiling: Chen superposition,
            # effective coefficient referenced to (T_wc - T_bulk)
            S = co.chen_suppression(Re)
            try:
                h_fz = co.forster_zuber(cool, st.p, T_wc, st.T_sat)
                dT_w = max(T_wc - st.T, 1e-3)
                h_conv = h_conv + S * h_fz * (T_wc - st.T_sat) / dT_w
                regime = "nucleate_boiling"
            except Exception as exc:
                log.debug("Forster-Zuber boiling correction skipped: %s", exc)
        return h_conv, Re, f, regime

    # ----------------------------------------------------------- marching
    def solve(self) -> pd.DataFrame:
        lay, cool, hot = self.lay, self.coolant, self.hot
        n = len(lay.x)
        eps_area = (lay.r / lay.r_throat) ** 2
        M = hot.mach_profile(lay.x, lay.r, lay.x_throat)
        T_aw = hot.t_aw(M)
        g = hot.g
        p_gas = hot.pc * (1.0 + 0.5 * (g - 1.0) * M * M) ** (-g / (g - 1.0))

        if self.cfg.film is not None:
            # first-order film relief: exponential effectiveness decay
            # downstream of the injection station (see FilmCfg)
            fc = self.cfg.film
            x_inj = (fc.injection_x_m if fc.injection_x_m is not None
                     else float(lay.x.min()))
            downstream = np.maximum(lay.x - x_inj, 0.0)
            eta = np.where(
                lay.x >= x_inj,
                np.exp(-downstream / fc.effectiveness_length_m), 0.0)
            T_aw = eta * fc.film_temp_K + (1.0 - eta) * T_aw

        if self.cfg.inlet.location == "nozzle_end":
            idx = np.arange(n - 1, -1, -1)        # counterflow (typical)
            l_from_inlet = lay.l[-1] - lay.l
        else:
            idx = np.arange(n)
            l_from_inlet = lay.l

        p = self.cfg.inlet.pressure_bar * 1e5
        h_in = cool.h_pt(p, self.cfg.inlet.temperature_K)
        h = h_in

        rows = []
        warn_sat = False
        self.wall_solve_fallbacks = 0
        def _state(p_, h_, where):
            try:
                return cool.state_ph(p_, h_)
            except ValueError as exc:
                raise ValueError(
                    f"regen: coolant state failed at x={lay.x[where]*1e3:.1f} mm "
                    f"(p={p_/1e5:.2f} bar, h={h_/1e3:.1f} kJ/kg): {exc} — the channel "
                    "pressure or enthalpy left the fluid's valid range (pressure "
                    "collapse from boiling / choking?); raise the inlet pressure, "
                    "enlarge the channels or reduce the heat load") from exc

        for j in idx:
            st = _state(p, h, j)
            G = self.mdot_ch / lay.A[j]
            v = G / st.rho
            Dh = lay.Dh[j]
            aspect = min(lay.w[j], lay.h[j]) / max(lay.w[j], lay.h[j])
            x_over_D = max(l_from_inlet[j], 0.0) / Dh
            # correlations expect d / D_coil with D_coil = 2 * R_curve
            dD = (Dh / (2.0 * lay.R_curve[j])
                  if np.isfinite(lay.R_curve[j]) else 0.0)
            rel_rough = self.cfg.roughness / Dh

            def a_cool(hc):
                eta = co.fin_efficiency(hc, self.k_wall(0.5 * (st.T + 700.0)),
                                        lay.t_rib[j], lay.h[j])
                return (lay.w[j] + 2.0 * eta * lay.h[j]) * lay.dl[j]

            def residual(T_wh):
                hg = hot.h_g(M[j], eps_area[j], T_wh)
                q2 = hg * (T_aw[j] - T_wh)
                kw = self.k_wall(T_wh)
                T_wc = T_wh - q2 * lay.t_wall[j] / kw
                hc, *_ = self._h_c(st, T_wc, G, Dh, dD, rel_rough, aspect, x_over_D)
                return q2 * lay.dA_hot[j] - hc * a_cool(hc) * (T_wc - st.T)

            lo, hi = st.T + 0.5, T_aw[j] - 0.5
            try:
                T_wh = brentq(residual, lo, hi, xtol=0.05,
                              maxiter=self.cfg.max_iter_wall)
            except ValueError:
                self.wall_solve_fallbacks += 1
                T_wh = hi if residual(hi) > 0 else lo
                log.warning("regen wall solve fell back to a bracket end at "
                            "x=%.4f m (T_wh=%.0f K)", lay.x[j], T_wh)

            hg = hot.h_g(M[j], eps_area[j], T_wh)
            q2 = hg * (T_aw[j] - T_wh)
            kw = self.k_wall(T_wh)
            T_wc = T_wh - q2 * lay.t_wall[j] / kw
            hc, Re, f, regime = self._h_c(st, T_wc, G, Dh, dD, rel_rough, aspect, x_over_D)
            Q = q2 * lay.dA_hot[j]
            # coolant-side heat for the same cell — the wall-solve residual;
            # differs from Q by the brentq tolerance / bracket fallbacks
            Q_cold = hc * a_cool(hc) * (T_wc - st.T)

            dp_fric = f * lay.dl[j] / Dh * 0.5 * st.rho * v * v
            h_new = h + Q / self.mdot_ch
            st2 = _state(max(p - dp_fric, 1e4), h_new, j)
            dp_acc = G * G * (1.0 / st2.rho - 1.0 / st.rho)
            p_new = p - dp_fric - dp_acc
            st_out = _state(max(p_new, 1e4), h_new, j)

            if 0.0 <= st.quality <= 1.0:
                warn_sat = True

            mach_c = v / st.a if (st.a and np.isfinite(st.a) and st.a > 0) else np.nan

            sig_th = sig_p = sig_tot = yield_mpa = ratio = strain = np.nan
            if self.stress_props is not None:
                E, alpha, nu, yfn = self.stress_props
                k_mean = self.k_wall(0.5 * (T_wh + T_wc))
                sig_th = co.thermal_stress_MPa(E, alpha, q2, lay.t_wall[j], k_mean, nu)
                sig_p = co.pressure_bending_stress_MPa(p - p_gas[j], lay.w[j], lay.t_wall[j])
                sig_tot = sig_th + abs(sig_p)
                yield_mpa = yfn(T_wh)
                ratio = sig_tot / max(yield_mpa, 1e-9)
                # hot-face thermal strain against the cold structure (LCF driver)
                strain = alpha * (T_wh - st.T)

            rows.append(dict(
                i=j, x_m=lay.x[j], r_m=lay.r[j], mach=M[j], T_aw_K=T_aw[j],
                h_g=hg, q_w_W_m2=q2, T_wall_hot_K=T_wh, T_wall_cold_K=T_wc,
                h_c=hc, Re=Re, f_darcy=f, regime=regime,
                T_cool_K=st.T, T_cool_out_K=st_out.T, p_cool_bar=p / 1e5,
                p_cool_out_bar=p_new / 1e5, h_J_kg=h, h_out_J_kg=h_new,
                rho=st.rho, rho_out=st_out.rho, v_m_s=v, mach_cool=mach_c,
                quality=st.quality,
                T_sat_K=st.T_sat, dp_cell_bar=(dp_fric + dp_acc) / 1e5,
                Q_cell_W=Q, Q_cold_cell_W=Q_cold, p_gas_bar=p_gas[j] / 1e5,
                sigma_thermal_MPa=sig_th, sigma_pressure_MPa=sig_p,
                sigma_total_MPa=sig_tot, yield_MPa=yield_mpa, stress_ratio=ratio,
                thermal_strain=strain,
            ))
            p, h = p_new, h_new

        df = pd.DataFrame(rows).sort_values("x_m").reset_index(drop=True)
        q_kw = float(df.Q_cell_W.sum()) * lay.N / 1e3
        q_cold_kw = float(df.Q_cold_cell_W.sum()) * lay.N / 1e3
        st_final = cool.state_ph(p, h)
        dh = h - h_in
        n_lam = int((df.Re < co.RE_LAMINAR).sum())
        n_trans = int(((df.Re >= co.RE_LAMINAR) & (df.Re < co.RE_TURBULENT)).sum())
        # Closure = hot-side vs coolant-side heat over the wall solve. The
        # marching Δh equals ΣQ_hot/mdot by construction, so comparing those
        # two would always be exactly zero and could never flag a problem.
        df.attrs.update(
            mdot_total=self.mdot_total, mdot_channel=self.mdot_ch,
            saturation_reached=warn_sat, outlet_p_bar=p / 1e5,
            outlet_T_K=st_final.T, inlet_T_K=self.cfg.inlet.temperature_K,
            inlet_h_kJ_kg=h_in / 1e3, outlet_h_kJ_kg=h / 1e3,
            dh_kJ_kg=dh / 1e3, Q_total_kW=q_kw, Q_total_cold_kW=q_cold_kw,
            energy_balance_kW=q_kw - q_cold_kw,
            mdot_engine=self.hot.mdot,
            coolant_inlet_location=self.cfg.inlet.location,
            coolant_side=self.coolant_side,
            coolant_correlation=self.correlation,
            wall_solve_fallbacks=self.wall_solve_fallbacks,
            n_laminar_stations=n_lam, n_transitional_stations=n_trans,
            coolant_mach_max=float(np.nanmax(df.mach_cool)) if df.mach_cool.notna().any() else float("nan"),
            wall_limit_K=self.wall_limit, wall_limit_source=self.wall_limit_source,
            wall_material=self.material.name if self.material else self.cfg.wall.material,
            wall_k_source=self.k_source,
            hot_gas_property_note=self.hot.property_note,
            hot_gas_fallback_properties=self.hot.uses_fallback_properties,
            hot_gas_r_curv_m=self.hot.r_curv,
            bartz_correction=self.cfg.hot_gas.bartz_correction,
            bartz_tol=self.cfg.hot_gas.bartz_correction_tol,
            sigma_max_MPa=float(np.nanmax(df.sigma_total_MPa)) if self.stress_props else float("nan"),
            stress_ratio_max=float(np.nanmax(df.stress_ratio)) if self.stress_props else float("nan"),
            thermal_strain_max=float(np.nanmax(df.thermal_strain)) if self.stress_props else float("nan"),
            stress_checked=self.stress_props is not None,
            stress_ratio_warn=self.cfg.wall.stress_ratio_warn,
        )
        return df
