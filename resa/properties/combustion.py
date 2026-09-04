"""Combustion model: properties as a function of O/F (and Pc for rocketcea).

build_model() returns a CombustionModel with

    .at(of, pc_bar)            -> CombustionResult (c*, Tc, gamma, MW)
    .nozzle(of, pc_bar, eps)   -> NozzleState (ideal vacuum CF, pe/pc, Me)
    .eps_for_pe(of, pc, pe)    -> (eps, NozzleState) for a target exit pressure
    .transport(of, pc_bar)     -> chamber transport properties (or None)
    .reference(of, pc_bar, eps)-> ideal Isp under every nozzle-flow model

so downstream code (sizing, O/F optimization, throttle sweeps, regen hot-gas
model) is backend-agnostic.

backend='table'    : interpolate the team's CEA table over O/F. A single-point
                     table works for fixed-O/F design but NOT for optimization
                     or sweeps (raises with a clear message). Nozzle expansion
                     is always the single-gamma isentropic model.
backend='rocketcea': live CEA per call (needs fortran toolchain). Nozzle
                     expansion per combustion.nozzle_flow: single_gamma,
                     equilibrium, frozen (at chamber) or frozen_at_throat.
                     With combustion.use_delivery_temperatures the propellant
                     cards are built at propellants.*_temp_K / *_phase instead
                     of rocketcea's reference states (LOX 90 K, LH2 20 K, ...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import numpy as np

from ..config.schema import CombustionConfig, PropellantConfig
from ..models.gasdynamics import (
    area_ratio_from_mach,
    cf_vacuum_single_gamma,
    critical_pressure_ratio,
    mach_from_pressure_ratio,
)
from ..results import CombustionResult, NozzleState

_R_UNIVERSAL = 8314.462618  # J/(kmol·K)
_G0 = 9.80665
_CAL = 4.184                # J/cal
_ATM = 101325.0

NOZZLE_FLOWS = ("single_gamma", "equilibrium", "frozen", "frozen_at_throat")
_FROZEN_FLAGS = {"equilibrium": (0, 0), "frozen": (1, 0), "frozen_at_throat": (1, 1)}


# --------------------------------------------------------------------------- #
# single-gamma nozzle (shared by both backends)
# --------------------------------------------------------------------------- #
def single_gamma_nozzle(eps: float, g: float) -> NozzleState:
    cf_vac, pr, Me = cf_vacuum_single_gamma(eps, g)
    return NozzleState(cf_vac=cf_vac, pe_over_pc=pr, exit_mach=Me,
                       gamma_exit=g, source="single_gamma")


def single_gamma_eps_for_pe(pc_over_pe: float, g: float) -> float:
    Me = mach_from_pressure_ratio(pc_over_pe, g)
    return float(area_ratio_from_mach(Me, g))


def check_supersonic_exit(pc_pa: float, pe_pa: float, g: float) -> None:
    """The exit must be supersonic: pe below the critical (choking) pressure."""
    p_crit = pc_pa * critical_pressure_ratio(g)
    if pe_pa >= p_crit:
        raise ValueError(
            f"design exit pressure {pe_pa/1e5:.3f} bar is above the choking "
            f"limit {p_crit/1e5:.3f} bar (gamma={g:.3f}) — the nozzle exit "
            "would be subsonic; lower pe_bar (or give eps directly)"
        )


# --------------------------------------------------------------------------- #
# TABLE backend
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TableModel:
    of_grid: np.ndarray | None       # None -> single point
    cstar: np.ndarray
    tc: np.ndarray
    gamma: np.ndarray
    mw: np.ndarray
    mu: np.ndarray | None = None
    pr: np.ndarray | None = None
    cp: np.ndarray | None = None
    source: str = "table"
    nozzle_flow: str = "single_gamma"

    @property
    def of_range(self) -> tuple[float, float]:
        if self.of_grid is None:
            raise ValueError(
                "combustion table is a single point — O/F optimization and "
                "sweeps need a table over O/F (give `of:` as a list)"
            )
        return float(self.of_grid[0]), float(self.of_grid[-1])

    def _interp(self, of: float, arr: np.ndarray) -> float:
        if self.of_grid is None:
            return float(arr[0])
        lo, hi = self.of_range
        if not (lo - 1e-9 <= of <= hi + 1e-9):
            raise ValueError(
                f"O/F={of:.3f} outside combustion table [{lo}, {hi}] — "
                "extend the table (no extrapolation, accuracy first)"
            )
        return float(np.interp(of, self.of_grid, arr))

    def at(self, of: float, pc_bar: float | None = None) -> CombustionResult:
        cstar, tc, g, mw = (self._interp(of, a)
                            for a in (self.cstar, self.tc, self.gamma, self.mw))
        return CombustionResult(
            cstar_ideal_m_s=cstar, tc_K=tc, gamma=g, mw_kg_kmol=mw,
            R_specific=_R_UNIVERSAL / mw, source=self.source,
            ox_state="table", fuel_state="table", nozzle_flow=self.nozzle_flow,
        )

    def nozzle(self, of: float, pc_bar: float, eps: float) -> NozzleState:
        return single_gamma_nozzle(eps, self.at(of, pc_bar).gamma)

    def eps_for_pe(self, of: float, pc_bar: float, pe_bar: float
                   ) -> tuple[float, NozzleState]:
        g = self.at(of, pc_bar).gamma
        check_supersonic_exit(pc_bar * 1e5, pe_bar * 1e5, g)
        eps = single_gamma_eps_for_pe(pc_bar / pe_bar, g)
        return eps, single_gamma_nozzle(eps, g)

    def transport(self, of: float, pc_bar: float | None = None) -> dict | None:
        if self.mu is None or self.pr is None:
            return None
        cp = self._interp(of, self.cp) if self.cp is not None else None
        mu = self._interp(of, self.mu)
        pr = self._interp(of, self.pr)
        return {
            "cp_frozen_J_kgK": cp, "mu_Pa_s": mu, "pr_frozen": pr,
            "k_frozen_W_mK": (cp * mu / pr) if cp is not None else None,
            "mu_throat_Pa_s": None,
        }

    def reference(self, of: float, pc_bar: float, eps: float) -> dict | None:
        return None

    @property
    def card_info(self) -> dict:
        return {}


# --------------------------------------------------------------------------- #
# ROCKETCEA backend
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=32)
def _cea_obj(ox: str, fuel: str):
    from rocketcea.cea_obj_w_units import CEA_Obj  # noqa: deferred import
    return CEA_Obj(
        oxName=ox, fuelName=fuel,
        isp_units="sec", cstar_units="m/s", pressure_units="bar",
        temperature_units="K", sonic_velocity_units="m/s",
        enthalpy_units="kJ/kg", density_units="kg/m^3",
        specific_heat_units="J/kg-K", viscosity_units="poise",
        thermal_cond_units="W/cm-degC",
    )


# --- propellant reference-state cards ----------------------------------------
_CARD_H = re.compile(r"h,cal\s*=\s*([-+0-9.eE]+)")
_CARD_T = re.compile(r"t\(k\)\s*=\s*([-+0-9.eE]+)")

# rocketcea cards whose reference state is a gas / a liquid, per CoolProp fluid
_GAS_CARDS = {"hydrogen": "GH2", "oxygen": "GOX", "nitrousoxide": "N2O"}
_LIQ_CARDS = {"hydrogen": "H2", "oxygen": "O2", "ethanol": "Ethanol",
              "methane": "CH4"}
# CoolProp fluid to evaluate the enthalpy shift of a LIQUID reference card
# (the CEA LH2 card is parahydrogen; CoolProp 'Hydrogen' is normal hydrogen)
_LIQ_SHIFT_FLUID = {"hydrogen": "ParaHydrogen"}


def _norm(name: str) -> str:
    return re.sub(r"[\s_\-()]", "", name).lower()


@dataclass(frozen=True)
class CardInfo:
    name: str            # rocketcea card name
    species: str         # e.g. 'H2(L)'
    elements: str        # e.g. 'H 2'
    h_cal: float
    t_K: float
    phase: str           # 'gas' | 'liquid' | 'unknown'

    def describe(self, note: str = "") -> str:
        ph = {"gas": "gas", "liquid": "liquid"}.get(self.phase, "")
        return f"{self.species} {ph} at {self.t_K:.1f} K{note}".replace("  ", " ")


def _lookup_card(name: str, role: str) -> Optional[CardInfo]:
    import rocketcea.input_cards as ic
    cards = ic.oxCards if role == "oxid" else ic.fuelCards
    lines = cards.get(name)
    if not lines:
        return None
    text = " ".join(lines)
    toks = lines[0].split()
    species = toks[1] if len(toks) > 1 else name
    elements = " ".join(t for t in toks[2:] if not t.startswith(("wt%", "h,cal", "t(k)", "rho")))
    mh, mt = _CARD_H.search(text), _CARD_T.search(text)
    if not (mh and mt):
        return None
    sp = species.upper()
    phase = "liquid" if "(L)" in sp else "gas" if "(G)" in sp else "unknown"
    return CardInfo(name=name, species=species, elements=elements,
                    h_cal=float(mh.group(1)), t_K=float(mt.group(1)), phase=phase)


def _coolprop_h(fluid: str, T: float, phase: str, p_hint: float) -> float:
    """Specific enthalpy [J/kg] of `fluid` at T in the requested phase."""
    from CoolProp.CoolProp import PropsSI
    if phase == "liquid":
        t_crit = PropsSI("TCRIT", fluid)
        if T >= t_crit:
            raise ValueError(
                f"{fluid} cannot be a liquid at {T:.1f} K (critical temperature "
                f"{t_crit:.1f} K) — set the phase to gas")
        return PropsSI("H", "T", T, "Q", 0, fluid)
    # gas: at 1 atm when that is a gas state, else saturated vapour
    try:
        p_sat = PropsSI("P", "T", T, "Q", 1, fluid) if T < PropsSI("TCRIT", fluid) else np.inf
    except Exception:
        p_sat = np.inf
    p = min(_ATM, 0.9 * p_sat) if np.isfinite(p_sat) else min(_ATM, p_hint)
    return PropsSI("H", "T", T, "P", p, fluid)


def _phase_at(fluid: str, T: float, p: float) -> str:
    from CoolProp.CoolProp import PhaseSI
    try:
        ph = PhaseSI("T", T, "P", p, fluid)
    except Exception:
        return "gas"
    return "liquid" if "liquid" in ph else "gas"


def _delivery_card(role: str, coolprop_name: str, cea_name: str, T: float,
                   phase: Optional[str], p_hint_pa: float) -> tuple[str, str]:
    """Register a rocketcea card for `coolprop_name` delivered at T (K) and
    return (card_name, description). The enthalpy is shifted from a reference
    card of the same species with CoolProp, so any state CoolProp can evaluate
    (warm gas, cold liquid, supercritical) is supported."""
    from CoolProp.CoolProp import PropsSI
    from rocketcea.cea_obj import add_new_fuel, add_new_oxidizer
    key = _norm(coolprop_name)
    phase = phase or _phase_at(coolprop_name, T, p_hint_pa)
    candidates = [cea_name]
    candidates += [c for c in ((_GAS_CARDS if phase == "gas" else _LIQ_CARDS).get(key),
                               (_LIQ_CARDS if phase == "gas" else _GAS_CARDS).get(key))
                   if c]
    infos = [ci for ci in (_lookup_card(c, role) for c in dict.fromkeys(candidates)) if ci]
    if not infos:
        raise ValueError(
            f"no rocketcea card found for {cea_name!r} — cannot build a "
            f"delivery-temperature card for {coolprop_name}")
    base = next((ci for ci in infos if ci.phase == phase), infos[0])
    base_phase = base.phase if base.phase != "unknown" else _phase_at(coolprop_name, base.t_K, _ATM)
    fluid = coolprop_name
    if base_phase == "liquid" and key in _LIQ_SHIFT_FLUID:
        fluid = _LIQ_SHIFT_FLUID[key]
    M = PropsSI("M", fluid)                                   # kg/mol
    dh = _coolprop_h(fluid, T, phase, p_hint_pa) - _coolprop_h(fluid, base.t_K, base_phase, _ATM)
    h_cal = base.h_cal + dh * M / _CAL
    species = re.sub(r"\((L|G)\)", "", base.species) + ("(G)" if phase == "gas" else "(L)")
    name = f"RESA_{_norm(cea_name).upper()}_{T:.1f}K_{phase[0].upper()}"
    card = f"{role} {species}  {base.elements}  wt%=100.\n h,cal={h_cal:.2f}  t(k)={T:.2f}\n"
    _register_card(role, name, card)
    desc = f"{species} at {T:.1f} K (delivery state, h={h_cal:.0f} cal/mol)"
    return name, desc


def _register_card(role: str, name: str, card: str) -> None:
    """Register once: rocketcea clears its whole run cache when an existing
    name is re-registered, which would orphan the cached CEA objects."""
    import rocketcea.input_cards as ic
    from rocketcea.cea_obj import add_new_fuel, add_new_oxidizer
    cards = ic.oxCards if role == "oxid" else ic.fuelCards
    lines = [" " + ln.strip() + " " for ln in card.split("\n") if ln.strip()]
    if cards.get(name) == lines:
        return
    if name in cards:
        _cea_obj.cache_clear()
    (add_new_oxidizer if role == "oxid" else add_new_fuel)(name, card)


@dataclass(frozen=True)
class CeaModel:
    ox: str
    fuel: str
    nozzle_flow: str = "single_gamma"
    eps_hint: float = 3.0
    source: str = "rocketcea"
    ox_state: str = ""
    fuel_state: str = ""
    card_info: dict = None   # type: ignore[assignment]

    @property
    def of_range(self) -> tuple[float, float]:
        return 0.5, 12.0

    def _cea(self):
        return _cea_obj(self.ox, self.fuel)

    def _flags(self) -> tuple[int, int]:
        return _FROZEN_FLAGS.get(self.nozzle_flow, (0, 0))

    def at(self, of: float, pc_bar: float | None = None) -> CombustionResult:
        pc = pc_bar or 25.0
        cea = self._cea()
        mw, g = cea.get_Chamber_MolWt_gamma(Pc=pc, MR=of, eps=self.eps_hint)
        tc = cea.get_Tcomb(Pc=pc, MR=of)
        if self.nozzle_flow == "frozen":
            # composition frozen at the chamber: use the matching (lower) c*
            # so mdot, CF and Isp are mutually consistent
            _, cstar, _ = cea.get_IvacCstrTc(Pc=pc, MR=of, eps=self.eps_hint,
                                             frozen=1, frozenAtThroat=0)
        else:
            cstar = cea.get_Cstar(Pc=pc, MR=of)
        return CombustionResult(
            cstar_ideal_m_s=float(cstar), tc_K=float(tc), gamma=float(g),
            mw_kg_kmol=float(mw), R_specific=_R_UNIVERSAL / float(mw),
            source=self.source, ox_state=self.ox_state, fuel_state=self.fuel_state,
            nozzle_flow=self.nozzle_flow,
        )

    def _cea_nozzle(self, of: float, pc_bar: float, eps: float, flow: str
                    ) -> NozzleState:
        cea = self._cea()
        fr, fat = _FROZEN_FLAGS[flow]
        isp_vac, cstar, _ = cea.get_IvacCstrTc(Pc=pc_bar, MR=of, eps=eps,
                                                frozen=fr, frozenAtThroat=fat)
        pc_ov_pe = cea.get_PcOvPe(Pc=pc_bar, MR=of, eps=eps, frozen=fr, frozenAtThroat=fat)
        Me = cea.get_MachNumber(Pc=pc_bar, MR=of, eps=eps, frozen=fr, frozenAtThroat=fat)
        _, ge = cea.get_exit_MolWt_gamma(Pc=pc_bar, MR=of, eps=eps, frozen=fr, frozenAtThroat=fat)
        return NozzleState(cf_vac=float(isp_vac) * _G0 / float(cstar),
                           pe_over_pc=1.0 / float(pc_ov_pe), exit_mach=float(Me),
                           gamma_exit=float(ge), source=f"cea_{flow}")

    def nozzle(self, of: float, pc_bar: float, eps: float) -> NozzleState:
        if self.nozzle_flow == "single_gamma":
            return single_gamma_nozzle(eps, self.at(of, pc_bar).gamma)
        return self._cea_nozzle(of, pc_bar, eps, self.nozzle_flow)

    def eps_for_pe(self, of: float, pc_bar: float, pe_bar: float
                   ) -> tuple[float, NozzleState]:
        g = self.at(of, pc_bar).gamma
        check_supersonic_exit(pc_bar * 1e5, pe_bar * 1e5, g)
        if self.nozzle_flow == "single_gamma":
            eps = single_gamma_eps_for_pe(pc_bar / pe_bar, g)
            return eps, single_gamma_nozzle(eps, g)
        fr, fat = self._flags()
        eps = float(self._cea().get_eps_at_PcOvPe(
            Pc=pc_bar, MR=of, PcOvPe=pc_bar / pe_bar, frozen=fr, frozenAtThroat=fat))
        return eps, self._cea_nozzle(of, pc_bar, eps, self.nozzle_flow)

    def transport(self, of: float, pc_bar: float | None = None) -> dict:
        """Chamber transport properties, frozen and equilibrium basis (SI)."""
        pc = pc_bar or 25.0
        cea = self._cea()
        cp_f, mu_f, k_f, pr_f = cea.get_Chamber_Transport(Pc=pc, MR=of, eps=self.eps_hint, frozen=1)
        cp_e, mu_e, k_e, pr_e = cea.get_Chamber_Transport(Pc=pc, MR=of, eps=self.eps_hint, frozen=0)
        _, mu_t, _, _ = cea.get_Throat_Transport(Pc=pc, MR=of, eps=self.eps_hint, frozen=1)
        return {
            "cp_frozen_J_kgK": float(cp_f), "mu_Pa_s": float(mu_f) * 0.1,   # poise -> Pa s
            "k_frozen_W_mK": float(k_f) * 100.0,                          # W/cm K -> W/m K
            "pr_frozen": float(pr_f),
            "cp_eq_J_kgK": float(cp_e), "k_eq_W_mK": float(k_e) * 100.0,
            "pr_eq": float(pr_e),
            "mu_throat_Pa_s": float(mu_t) * 0.1,
        }

    def reference(self, of: float, pc_bar: float, eps: float) -> dict:
        """Ideal vacuum Isp [s] of every nozzle-flow model at this point."""
        comb_eq_cstar = float(self._cea().get_Cstar(Pc=pc_bar, MR=of))
        g = self.at(of, pc_bar).gamma
        out = {"single_gamma": single_gamma_nozzle(eps, g).cf_vac * comb_eq_cstar / _G0}
        for flow in ("equilibrium", "frozen", "frozen_at_throat"):
            fr, fat = _FROZEN_FLAGS[flow]
            isp, _, _ = self._cea().get_IvacCstrTc(Pc=pc_bar, MR=of, eps=eps,
                                                   frozen=fr, frozenAtThroat=fat)
            out[flow] = float(isp)
        return out


CombustionModel = TableModel | CeaModel


def build_model(
    prop: PropellantConfig,
    comb: CombustionConfig,
    *,
    ox_temp_K: float | None = None,
    fuel_temp_K: float | None = None,
    pc_hint_bar: float = 25.0,
) -> CombustionModel:
    """Build the combustion model. Delivery temperatures default to the
    propellant config values and only matter for rocketcea with
    combustion.use_delivery_temperatures."""
    if comb.backend == "table":
        t = comb.table
        as_arr = lambda v: np.atleast_1d(np.asarray(v, dtype=float))
        opt = lambda v: None if v is None else as_arr(v)
        return TableModel(
            of_grid=None if t.of is None else np.asarray(t.of, dtype=float),
            cstar=as_arr(t.cstar_m_s), tc=as_arr(t.tc_K),
            gamma=as_arr(t.gamma), mw=as_arr(t.mw_kg_kmol),
            mu=opt(t.mu_pa_s), pr=opt(t.pr), cp=opt(t.cp_J_kgK),
        )
    if comb.backend == "rocketcea":
        try:
            import rocketcea  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "backend='rocketcea' needs rocketcea installed (fortran "
                "toolchain). Use backend='table' otherwise."
            ) from e
        ox = prop.cea_oxidizer or prop.oxidizer
        fuel = prop.cea_fuel or prop.fuel
        info = {}
        ox_info, fuel_info = _lookup_card(ox, "oxid"), _lookup_card(fuel, "fuel")
        ox_state = ox_info.describe(" (CEA default)") if ox_info else f"{ox} (CEA default)"
        fuel_state = fuel_info.describe(" (CEA default)") if fuel_info else f"{fuel} (CEA default)"
        if ox_info:
            info["oxidizer"] = ox_info
        if fuel_info:
            info["fuel"] = fuel_info
        if comb.use_delivery_temperatures:
            T_ox = round(float(ox_temp_K if ox_temp_K is not None else prop.ox_temp_K), 1)
            T_f = round(float(fuel_temp_K if fuel_temp_K is not None else prop.fuel_temp_K), 1)
            p_hint = pc_hint_bar * 1e5
            ox, ox_state = _delivery_card("oxid", prop.oxidizer, ox, T_ox, prop.ox_phase, p_hint)
            fuel, fuel_state = _delivery_card("fuel", prop.fuel, fuel, T_f, prop.fuel_phase, p_hint)
        return CeaModel(ox=ox, fuel=fuel, nozzle_flow=comb.nozzle_flow,
                        ox_state=ox_state, fuel_state=fuel_state, card_info=info)
    raise ValueError(f"unknown combustion backend {comb.backend!r}")
