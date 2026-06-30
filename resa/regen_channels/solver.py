"""1D enthalpy-marching finite-volume regen solver with regime switching.

Per cell, marching along the coolant flow direction:
  1. Bulk state from (p, h) via CoolProp.
  2. Coolant HTC: Gnielinski baseline; Jackson supercritical correction at
     p > p_crit; Chen-style superposition (suppressed Forster-Zuber + forced
     convection) when the cold wall exceeds T_sat at subcritical pressure.
     Helix curvature enhances both HTC (Schmidt) and friction (Ito).
  3. Wall energy balance solved per station with brentq on T_wall_hot:
         q'' = h_g(T_wh) * (T_aw - T_wh)                 [Bartz, sigma(T_wh)]
         T_wc = T_wh - q'' * t_wall / k_wall(T)
         q'' * dA_hot = h_c(T_wc) * (w + 2*eta_fin*h) * dl * (T_wc - T_b)
  4. Update h (energy) and p (friction + acceleration + curvature).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from . import correlations as co
from .coolant import Coolant
from .hotgas import HotGas
from .layout import ChannelLayout

log = logging.getLogger(__name__)


class RegenSolver:
    def __init__(self, layout: ChannelLayout, cfg):
        self.lay = layout
        self.cfg = cfg.solver
        self.coolant = Coolant(self.cfg.coolant)

        # hot-gas model anchored at the full-contour throat
        Dt = 2.0 * layout.r_throat
        r_curv = 0.94 * Dt   # blend of 1.5*Rt / 0.382*Rt arcs; only ^0.1 power
        self.hot = HotGas(self.cfg.hot_gas, layout.A_throat, Dt, r_curv)

        # wall conductivity callable
        cond = self.cfg.wall.conductivity
        if cond == "inconel718":
            self.k_wall = co.k_inconel718
        else:
            val = float(cond)
            self.k_wall = lambda T: val

        # coolant mass flow
        if self.cfg.mdot_total is not None:
            self.mdot_total = self.cfg.mdot_total
        elif self.cfg.mdot_from_engine:
            frac = (self.cfg.coolant_fraction
                    if self.cfg.coolant_fraction is not None
                    else self.cfg.of_ratio / (1.0 + self.cfg.of_ratio))
            self.mdot_total = self.hot.mdot * frac
        else:
            raise ValueError("Set solver.mdot_total or mdot_from_engine")
        self.mdot_ch = self.mdot_total / layout.N

    # ----------------------------------------------------------------- HTC
    def _h_c(self, st, T_wc: float, G: float, Dh: float, d_over_D: float,
             rel_rough: float):
        """Coolant heat transfer coefficient at given cold-wall temperature.
        Returns (h_c, Re, f_darcy, regime)."""
        Re = G * Dh / st.mu
        f = co.churchill_f(Re, rel_rough)
        if self.cfg.curvature_enhancement:
            f = co.ito_curvature_friction(f, Re, d_over_D)
        Nu = co.gnielinski(Re, st.Pr, f)
        regime = "single_phase"
        cool = self.coolant

        if st.is_supercritical_p:
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
                h_conv *= co.curvature_htc_factor(Re, d_over_D)
            return h_conv, Re, f, regime

        h_conv = Nu * st.k / Dh
        if self.cfg.curvature_enhancement:
            h_conv *= co.curvature_htc_factor(Re, d_over_D)

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

        if self.cfg.inlet.location == "nozzle_end":
            idx = np.arange(n - 1, -1, -1)        # counterflow (typical)
        else:
            idx = np.arange(n)

        p = self.cfg.inlet.pressure_bar * 1e5
        h_in = cool.h_pt(p, self.cfg.inlet.temperature_K)
        h = h_in

        rows = []
        warn_sat = False
        for j in idx:
            st = cool.state_ph(p, h)
            G = self.mdot_ch / lay.A[j]
            v = G / st.rho
            Dh = lay.Dh[j]
            dD = Dh / lay.R_curve[j] if np.isfinite(lay.R_curve[j]) else 0.0
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
                hc, *_ = self._h_c(st, T_wc, G, Dh, dD, rel_rough)
                return q2 * lay.dA_hot[j] - hc * a_cool(hc) * (T_wc - st.T)

            lo, hi = st.T + 0.5, T_aw[j] - 0.5
            try:
                T_wh = brentq(residual, lo, hi, xtol=0.05, maxiter=200)
            except ValueError:
                T_wh = hi if residual(hi) > 0 else lo

            hg = hot.h_g(M[j], eps_area[j], T_wh)
            q2 = hg * (T_aw[j] - T_wh)
            T_wc = T_wh - q2 * lay.t_wall[j] / self.k_wall(T_wh)
            hc, Re, f, regime = self._h_c(st, T_wc, G, Dh, dD, rel_rough)
            Q = q2 * lay.dA_hot[j]

            dp_fric = f * lay.dl[j] / Dh * 0.5 * st.rho * v * v
            h_new = h + Q / self.mdot_ch
            st2 = cool.state_ph(max(p - dp_fric, 1e4), h_new)
            dp_acc = G * G * (1.0 / st2.rho - 1.0 / st.rho)
            p_new = p - dp_fric - dp_acc
            st_out = cool.state_ph(max(p_new, 1e4), h_new)

            if 0.0 <= st.quality <= 1.0:
                warn_sat = True

            rows.append(dict(
                i=j, x_m=lay.x[j], r_m=lay.r[j], mach=M[j], T_aw_K=T_aw[j],
                h_g=hg, q_w_W_m2=q2, T_wall_hot_K=T_wh, T_wall_cold_K=T_wc,
                h_c=hc, Re=Re, f_darcy=f, regime=regime,
                T_cool_K=st.T, T_cool_out_K=st_out.T, p_cool_bar=p / 1e5,
                p_cool_out_bar=p_new / 1e5, h_J_kg=h, h_out_J_kg=h_new,
                rho=st.rho, rho_out=st_out.rho, v_m_s=v, quality=st.quality,
                T_sat_K=st.T_sat, dp_cell_bar=(dp_fric + dp_acc) / 1e5,
                Q_cell_W=Q,
            ))
            p, h = p_new, h_new

        df = pd.DataFrame(rows).sort_values("x_m").reset_index(drop=True)
        q_kw = float(df.Q_cell_W.sum()) * lay.N / 1e3
        st_final = cool.state_ph(p, h)
        dh = h - h_in
        df.attrs.update(
            mdot_total=self.mdot_total, mdot_channel=self.mdot_ch,
            saturation_reached=warn_sat, outlet_p_bar=p / 1e5,
            outlet_T_K=st_final.T, inlet_T_K=self.cfg.inlet.temperature_K,
            inlet_h_kJ_kg=h_in / 1e3, outlet_h_kJ_kg=h / 1e3,
            dh_kJ_kg=dh / 1e3, Q_total_kW=q_kw,
            energy_balance_kW=self.mdot_total * dh / 1e3 - q_kw,
            mdot_engine=self.hot.mdot,
            coolant_inlet_location=self.cfg.inlet.location,
        )
        return df
