"""Coolant thermophysical properties via CoolProp, with a transport-property
fallback for N2O.

CoolProp has a full Helmholtz EOS for NitrousOxide but NO viscosity /
conductivity model. N2O and CO2 are isoelectronic with near-identical molar
mass (44.013 vs 44.010 kg/kmol) and very close critical points, so an
extended-corresponding-states mapping onto CO2 at equal reduced temperature
and reduced density is an excellent engineering estimate:

    mu_N2O(T, rho) ~= mu_CO2(T * Tc_CO2/Tc_N2O, rho * rhoc_CO2/rhoc_N2O)

Swap in in-house fits here if preferred — only `transport()` changes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from CoolProp.CoolProp import PropsSI

_TC = {"N2O": 309.52, "CO2": 304.1282}
_RHOC = {"N2O": 452.011, "CO2": 467.6}

_N2O_NAMES = {"N2O", "NITROUSOXIDE", "NITROUS OXIDE"}


@dataclass
class CoolantState:
    T: float
    p: float
    h: float
    rho: float
    cp: float
    mu: float
    k: float
    Pr: float
    quality: float          # -1 single phase, 0..1 two-phase
    T_sat: float            # NaN above critical pressure
    is_supercritical_p: bool


class Coolant:
    def __init__(self, name: str):
        self.name = name
        self._is_n2o = name.upper().replace("_", "") in _N2O_NAMES \
            or name.upper() == "NITROUSOXIDE"
        self.cp_name = "NitrousOxide" if self._is_n2o else name
        self.p_crit = PropsSI("PCRIT", self.cp_name)
        self.T_crit = PropsSI("TCRIT", self.cp_name)

    # -- transport ---------------------------------------------------------
    def transport(self, T: float, rho: float):
        """(mu [Pa s], k [W/m/K]) from T, rho."""
        if not self._is_n2o:
            mu = PropsSI("V", "T", T, "D", rho, self.cp_name)
            k = PropsSI("L", "T", T, "D", rho, self.cp_name)
            return mu, k
        T_m = T * _TC["CO2"] / _TC["N2O"]
        rho_m = min(rho * _RHOC["CO2"] / _RHOC["N2O"], 1170.0)
        mu = PropsSI("V", "T", T_m, "D", rho_m, "CO2")
        k = PropsSI("L", "T", T_m, "D", rho_m, "CO2")
        return mu, k

    # -- bulk state from (p, h) ---------------------------------------------
    def state_ph(self, p: float, h: float) -> CoolantState:
        T = PropsSI("T", "P", p, "H", h, self.cp_name)
        rho = PropsSI("D", "P", p, "H", h, self.cp_name)
        try:
            q = PropsSI("Q", "P", p, "H", h, self.cp_name)
        except ValueError:
            q = -1.0
        if q is None or np.isnan(q):
            q = -1.0
        sc_p = p >= self.p_crit
        T_sat = float("nan") if sc_p else PropsSI("T", "P", p, "Q", 0, self.cp_name)

        if 0.0 <= q <= 1.0:   # two-phase bulk: homogeneous mixture props
            rl = PropsSI("D", "P", p, "Q", 0, self.cp_name)
            rv = PropsSI("D", "P", p, "Q", 1, self.cp_name)
            cpl = PropsSI("C", "P", p, "Q", 0, self.cp_name)
            cpv = PropsSI("C", "P", p, "Q", 1, self.cp_name)
            mul, kl = self.transport(T_sat, rl)
            muv, kv = self.transport(T_sat, rv)
            mu = 1.0 / (q / muv + (1 - q) / mul)       # McAdams
            k = (1 - q) * kl + q * kv
            cp = (1 - q) * cpl + q * cpv
        else:
            cp = PropsSI("C", "P", p, "H", h, self.cp_name)
            mu, k = self.transport(T, rho)
        return CoolantState(T=T, p=p, h=h, rho=rho, cp=cp, mu=mu, k=k,
                            Pr=cp * mu / k, quality=q, T_sat=T_sat,
                            is_supercritical_p=sc_p)

    def h_pt(self, p: float, T: float) -> float:
        return PropsSI("H", "P", p, "T", T, self.cp_name)

    def wall_props(self, p: float, T_w: float):
        """(rho_w, h_w, mu_w, k_w, cp_w) at wall temperature, bulk pressure.
        Liquid-side clamp at saturation for subcritical boiling handling."""
        T_w = min(max(T_w, 120.0), 1500.0)
        if p < self.p_crit:
            T_sat = PropsSI("T", "P", p, "Q", 0, self.cp_name)
            if T_w >= T_sat - 1e-3:
                # superheated film: evaluate vapour side
                rho = PropsSI("D", "P", p, "Q", 1, self.cp_name)
                hh = PropsSI("H", "P", p, "Q", 1, self.cp_name)
                mu, k = self.transport(T_sat, rho)
                cp = PropsSI("C", "P", p, "Q", 1, self.cp_name)
                return rho, hh, mu, k, cp
        rho = PropsSI("D", "P", p, "T", T_w, self.cp_name)
        hh = PropsSI("H", "P", p, "T", T_w, self.cp_name)
        mu, k = self.transport(T_w, rho)
        cp = PropsSI("C", "P", p, "T", T_w, self.cp_name)
        return rho, hh, mu, k, cp
