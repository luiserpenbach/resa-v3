"""NASA CEA backend (``combustion.backend: cea``).

Uses the open-source NASA CEA re-implementation (``pip install cea``, prebuilt
wheels, no Fortran toolchain) so RESA runs anywhere a wheel installs — including
serverless hosts where rocketcea cannot be compiled.

    equilibrium       CEA rocket problem (infinite-area combustor), shifting
                      equilibrium expansion
    frozen            composition frozen at the chamber; the expansion is
                      integrated here from CEA species thermodynamics
                      (isentropic, ideal gas, s(T, p) = s_chamber)
    frozen_at_throat  CEA equilibrium to the throat, frozen downstream
    single_gamma      isentropic relations with the chamber gamma

The frozen branches are integrated in RESA because cea 3.3's own frozen
rocket solve does not converge for common propellant pairs.

Propellant enthalpy is passed to the solver directly (``hc``): the reactant
species only fix the element balance. Delivery states follow the rocketcea
backend — CEA reference states by default, or propellants.*_temp_K / *_phase
(``combustion.use_delivery_temperatures``) with the enthalpy shifted from a
CEA reference species by CoolProp.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import numpy as np
from scipy.optimize import brentq, minimize_scalar

from ..results import CombustionResult, NozzleState

_G0 = 9.80665
_R_UNIVERSAL = 8314.462618
_T_STD = 298.15

# the CEA library keeps global Fortran state: serialize every call
_LOCK = threading.RLock()

NOZZLE_FLOWS = ("single_gamma", "equilibrium", "frozen", "frozen_at_throat")


@dataclass(frozen=True)
class PropellantSpec:
    key: str
    label: str
    gas: Optional[str]              # CEA gas species (element balance + h(T))
    liquid: Optional[str]           # CEA condensed species
    liquid_ref_T: Optional[float]   # reference temperature of the liquid species
    coolprop: Optional[str]         # CoolProp fluid for enthalpy shifts
    default_phase: str              # rocketcea-equivalent reference state
    default_T: float


PROPELLANTS: dict[str, PropellantSpec] = {s.key: s for s in (
    PropellantSpec("oxygen", "Oxygen", "O2", "O2(L)", 90.17, "Oxygen", "liquid", 90.17),
    PropellantSpec("hydrogen", "Hydrogen", "H2", "H2(L)", 20.27, "Hydrogen", "liquid", 20.27),
    PropellantSpec("nitrousoxide", "Nitrous oxide", "N2O", None, None, "NitrousOxide", "gas", _T_STD),
    PropellantSpec("ethanol", "Ethanol", "C2H5OH", "C2H5OH(L)", _T_STD, "Ethanol", "liquid", _T_STD),
    PropellantSpec("methanol", "Methanol", "CH3OH", "CH3OH(L)", _T_STD, "Methanol", "liquid", _T_STD),
    PropellantSpec("methane", "Methane", "CH4", "CH4(L)", 111.643, "Methane", "liquid", 111.643),
    PropellantSpec("propane", "Propane", "C3H8", "C3H8(L)", 231.08, "n-Propane", "liquid", 231.08),
    PropellantSpec("ammonia", "Ammonia", "NH3", "NH3(L)", 239.72, "Ammonia", "liquid", 239.72),
    PropellantSpec("rp1", "RP-1 (kerosene)", None, "RP-1", _T_STD, None, "liquid", _T_STD),
    PropellantSpec("jeta", "Jet-A", None, "Jet-A(L)", _T_STD, None, "liquid", _T_STD),
    PropellantSpec("isopropanol", "Isopropanol", "C3H8O,2propanol", None, None, None, "liquid", _T_STD),
    PropellantSpec("n2o4", "Nitrogen tetroxide", "N2O4", "N2O4(L)", _T_STD, None, "liquid", _T_STD),
    PropellantSpec("mmh", "MMH", None, "CH6N2(L)", _T_STD, None, "liquid", _T_STD),
    PropellantSpec("udmh", "UDMH", None, "C2H8N2(L),UDMH", _T_STD, None, "liquid", _T_STD),
    PropellantSpec("hydrazine", "Hydrazine", "N2H4", "N2H4(L)", _T_STD, None, "liquid", _T_STD),
    PropellantSpec("h2o2", "Hydrogen peroxide", "H2O2", "H2O2(L)", _T_STD, None, "liquid", _T_STD),
    PropellantSpec("water", "Water", "H2O", "H2O(L)", _T_STD, "Water", "liquid", _T_STD),
)}

# name (normalized) -> (key, forced phase or None). rocketcea card names keep
# rocketcea's meaning ('O2' / 'H2' are the cryogenic liquids).
_ALIASES: dict[str, tuple[str, Optional[str]]] = {
    "oxygen": ("oxygen", None), "o2": ("oxygen", "liquid"), "lox": ("oxygen", "liquid"),
    "o2l": ("oxygen", "liquid"), "gox": ("oxygen", "gas"), "o2g": ("oxygen", "gas"),
    "hydrogen": ("hydrogen", None), "parahydrogen": ("hydrogen", None),
    "h2": ("hydrogen", "liquid"), "lh2": ("hydrogen", "liquid"), "h2l": ("hydrogen", "liquid"),
    "gh2": ("hydrogen", "gas"), "h2g": ("hydrogen", "gas"),
    "nitrousoxide": ("nitrousoxide", None), "n2o": ("nitrousoxide", None),
    "ethanol": ("ethanol", None), "c2h5oh": ("ethanol", "liquid"), "c2h5ohl": ("ethanol", "liquid"),
    "methanol": ("methanol", None), "ch3oh": ("methanol", "liquid"),
    "methane": ("methane", None), "ch4": ("methane", "liquid"), "lch4": ("methane", "liquid"),
    "lch4nasa": ("methane", "liquid"), "gch4": ("methane", "gas"), "ch4l": ("methane", "liquid"),
    "propane": ("propane", None), "npropane": ("propane", None), "c3h8": ("propane", "liquid"),
    "ammonia": ("ammonia", None), "nh3": ("ammonia", "liquid"),
    "rp1": ("rp1", "liquid"), "kerosene": ("rp1", "liquid"), "ndodecane": ("rp1", "liquid"),
    "jeta": ("jeta", "liquid"), "jeta1": ("jeta", "liquid"),
    "isopropanol": ("isopropanol", None), "ipa": ("isopropanol", None),
    "n2o4": ("n2o4", "liquid"), "nto": ("n2o4", "liquid"),
    "mmh": ("mmh", "liquid"), "udmh": ("udmh", "liquid"),
    "hydrazine": ("hydrazine", "liquid"), "n2h4": ("hydrazine", "liquid"),
    "h2o2": ("h2o2", "liquid"), "hydrogenperoxide": ("h2o2", "liquid"),
    "water": ("water", None), "h2o": ("water", "liquid"),
}


def _norm(name: str) -> str:
    return re.sub(r"[\s_\-(),.]", "", name).lower()


def resolve_propellant(*names: Optional[str]) -> tuple[PropellantSpec, Optional[str]]:
    """First name that maps to a known propellant -> (spec, forced phase)."""
    for n in names:
        if not n:
            continue
        hit = _ALIASES.get(_norm(n))
        if hit:
            return PROPELLANTS[hit[0]], hit[1]
    raise ValueError(
        f"NASA CEA backend: unknown propellant {' / '.join(n for n in names if n)!r} — "
        f"supported: {', '.join(s.label for s in PROPELLANTS.values())}")


# --------------------------------------------------------------------------- #
# reactant states
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReactantState:
    species: str        # CEA species used for the element balance
    h_J_kg: float       # delivered specific enthalpy (CEA reference basis)
    t_K: float
    phase: str
    note: str

    def describe(self) -> str:
        return f"{self.species} {self.phase} at {self.t_K:.1f} K{self.note}"


def _species_h(species: str, T: float) -> float:
    import cea
    with _LOCK:
        return float(cea.Mixture([species]).calc_property(cea.ENTHALPY, np.array([1.0]), T))


def _liquid_range(species: str) -> tuple[float, float]:
    import cea
    with _LOCK:
        return tuple(cea.Reactant(species).get_valid_temperature_range())  # type: ignore[return-value]


def reactant_state(spec: PropellantSpec, T: Optional[float], phase: Optional[str],
                   p_hint_pa: float) -> ReactantState:
    """Delivered reactant state. T=None -> the CEA reference state of the
    propellant (the rocketcea default card equivalent)."""
    from .combustion import _LIQ_SHIFT_FLUID, _coolprop_h, _phase_at

    if T is None:
        phase = phase or spec.default_phase
        if phase == "liquid" and spec.liquid:
            return ReactantState(spec.liquid, _species_h(spec.liquid, spec.liquid_ref_T),
                                 spec.liquid_ref_T, "liquid", " (CEA reference)")
        sp = spec.gas or spec.liquid
        return ReactantState(sp, _species_h(sp, _T_STD), _T_STD,
                             "gas" if spec.gas else "liquid", " (CEA reference)")

    if phase is None:
        phase = _phase_at(spec.coolprop, T, p_hint_pa) if spec.coolprop else spec.default_phase
    # a condensed CEA species covers the state directly inside its data range
    if phase == "liquid" and spec.liquid:
        lo, hi = _liquid_range(spec.liquid)
        if lo <= T <= hi:
            return ReactantState(spec.liquid, _species_h(spec.liquid, T), T, "liquid", "")
    if spec.coolprop:
        # shift from a CEA reference species with CoolProp (any state CoolProp covers)
        if phase == "liquid" and spec.liquid:
            base_sp, base_T, base_phase = spec.liquid, spec.liquid_ref_T, "liquid"
        else:
            base_sp, base_T, base_phase = spec.gas or spec.liquid, _T_STD, "gas"
        fluid = spec.coolprop
        if base_phase == "liquid" and spec.key in _LIQ_SHIFT_FLUID:
            fluid = _LIQ_SHIFT_FLUID[spec.key]
        dh = _coolprop_h(fluid, T, phase, p_hint_pa) - _coolprop_h(fluid, base_T, base_phase, 101325.0)
        return ReactantState(base_sp, _species_h(base_sp, base_T) + dh, T, phase, "")
    # no CoolProp model: CEA species data, clamped to its valid range
    sp = spec.liquid if (phase == "liquid" and spec.liquid) else (spec.gas or spec.liquid)
    if sp == spec.liquid:
        lo, hi = _liquid_range(sp)
        Tc = float(np.clip(T, lo, hi))
    else:
        Tc = max(T, 200.0)
    note = "" if abs(Tc - T) < 0.05 else f" (CEA data limited to {Tc:.1f} K)"
    return ReactantState(sp, _species_h(sp, Tc), Tc, "liquid" if sp == spec.liquid else "gas", note)


# --------------------------------------------------------------------------- #
# CEA runs (module-level caches keyed on primitives)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=16)
def _solver(fuel_sp: str, ox_sp: str):
    import cea
    with _LOCK:
        cea.set_log_level(cea.LOG_NONE)
        reac = cea.Mixture([fuel_sp, ox_sp])
        prod = cea.Mixture([fuel_sp, ox_sp], products_from_reactants=True)
        solver = cea.RocketSolver(prod, reactants=reac, transport=True)
    return reac, prod, solver


def _weights(reac, of: float) -> np.ndarray:
    return reac.of_ratio_to_weights(np.array([0.0, 1.0]), np.array([1.0, 0.0]), of)


@dataclass(frozen=True)
class _Run:
    T: np.ndarray
    P: np.ndarray
    M: np.ndarray
    gamma_s: np.ndarray
    cp_fr: np.ndarray       # J/kg K
    cp_eq: np.ndarray
    mach: np.ndarray
    ae_at: np.ndarray
    cstar: float
    isp_vac: np.ndarray     # m/s
    son: np.ndarray
    rho: np.ndarray
    mu: np.ndarray          # Pa s
    k_fr: np.ndarray        # W/m K
    k_eq: np.ndarray
    pr_fr: np.ndarray
    pr_eq: np.ndarray
    w_chamber: np.ndarray   # product mass fractions (prod species order)
    w_throat: np.ndarray
    names: tuple = field(default=())


@lru_cache(maxsize=8192)
def _eq_run(fuel_sp: str, h_f: float, ox_sp: str, h_o: float, of: float, pc: float,
            supar: tuple = (), pi_p: tuple = ()) -> _Run:
    import cea
    reac, prod, solver = _solver(fuel_sp, ox_sp)
    with _LOCK:
        w = _weights(reac, of)
        hc = (w[0] * h_f + w[1] * h_o) / (w[0] + w[1])
        sol = cea.RocketSolution(solver)
        kw = {}
        if supar:
            kw["supar"] = list(supar)
        if pi_p:
            kw["pi_p"] = list(pi_p)
        solver.solve(sol, w, pc, iac=True, hc=hc / cea.R, **kw)
        if not sol.converged:
            raise ValueError(f"NASA CEA did not converge at O/F={of:.3f}, pc={pc:.2f} bar")
        names = tuple(prod.species_names)
        mf = sol.mass_fractions
        wc = np.array([mf[n][0] for n in names])
        wt = np.array([mf[n][1] for n in names])
        a = lambda v: np.array(v, dtype=float)
        return _Run(
            T=a(sol.T), P=a(sol.P), M=a(sol.M), gamma_s=a(sol.gamma_s),
            cp_fr=a(sol.cp_fr) * 1e3, cp_eq=a(sol.cp_eq) * 1e3, mach=a(sol.Mach),
            ae_at=a(sol.ae_at), cstar=float(a(sol.c_star)[0]), isp_vac=a(sol.Isp_vacuum),
            son=a(sol.sonic_velocity), rho=a(sol.density),
            mu=a(sol.viscosity) * 1e-4, k_fr=a(sol.conductivity_fr) * 0.1,
            k_eq=a(sol.conductivity_eq) * 0.1, pr_fr=a(sol.Pr_fr), pr_eq=a(sol.Pr_eq),
            w_chamber=wc, w_throat=wt, names=names,
        )


class _FrozenGas:
    """Ideal-gas mixture of fixed composition, isentropic from (T0, p0)."""

    def __init__(self, prod, w: np.ndarray, T0: float, p0_bar: float, u0: float = 0.0):
        import cea
        self._cea, self.prod, self.w = cea, prod, w / w.sum()
        with _LOCK:
            self.s0 = self._calc(cea.ENTROPY, T0, p0_bar)
            self.H0 = self._calc(cea.ENTHALPY, T0) + 0.5 * u0 * u0   # total enthalpy
            cp = self._calc(cea.FROZEN_CP, T0)
            cv = self._calc(cea.FROZEN_CV, T0)
        self.R = cp - cv
        self.T0, self.p0 = T0, p0_bar

    def _calc(self, prop, T, p=None):
        if p is None:
            return float(self.prod.calc_property(prop, self.w, T))
        return float(self.prod.calc_property(prop, self.w, T, p))

    def state(self, p_bar: float) -> tuple[float, float, float]:
        """(T, u, G = rho u) at static pressure p on the isentrope."""
        cea = self._cea
        with _LOCK:
            f = lambda T: self._calc(cea.ENTROPY, T, p_bar) - self.s0
            T_hi = self.T0 + 1.0
            if f(T_hi) <= 0:
                T = self.T0
            else:
                T_lo = max(0.5 * self.T0, 10.0)
                while f(T_lo) > 0 and T_lo > 10.0:
                    T_lo = max(0.5 * T_lo, 10.0)
                T = brentq(f, T_lo, T_hi, xtol=1e-4)
            h = self._calc(cea.ENTHALPY, T)
        u = float(np.sqrt(max(2.0 * (self.H0 - h), 0.0)))
        rho = p_bar * 1e5 / (self.R * T)
        return T, u, rho * u

    def gamma(self, T: float) -> float:
        cea = self._cea
        with _LOCK:
            cp, cv = self._calc(cea.FROZEN_CP, T), self._calc(cea.FROZEN_CV, T)
        return cp / cv


@lru_cache(maxsize=256)
def _frozen_throat(fuel_sp: str, h_f: float, ox_sp: str, h_o: float, of: float,
                   pc: float, at_throat: bool):
    """-> (FrozenGas, p_throat_bar, G_throat). Chamber-frozen: the throat is the
    mass-flux maximum on the frozen isentrope. Throat-frozen: CEA equilibrium
    throat state, frozen downstream."""
    run = _eq_run(fuel_sp, h_f, ox_sp, h_o, of, pc)
    _, prod, _ = _solver(fuel_sp, ox_sp)
    if at_throat:
        u_t = float(run.son[1])
        gas = _FrozenGas(prod, run.w_throat, float(run.T[1]), float(run.P[1]), u0=u_t)
        return gas, float(run.P[1]), float(run.rho[1]) * u_t
    gas = _FrozenGas(prod, run.w_chamber, float(run.T[0]), pc)
    res = minimize_scalar(lambda pr: -gas.state(pr * pc)[2], bounds=(0.3, 0.9),
                          method="bounded", options={"xatol": 1e-6})
    p_t = float(res.x) * pc
    return gas, p_t, gas.state(p_t)[2]


def _frozen_exit(gas: "_FrozenGas", p_t: float, G_t: float, pc: float,
                 eps: Optional[float] = None, pe: Optional[float] = None,
                 cstar: float = 0.0) -> tuple[NozzleState, float]:
    """Frozen supersonic exit at an area ratio or exit pressure -> (state, eps)."""
    if pe is None:
        f = lambda lp: G_t / gas.state(float(np.exp(lp)))[2] - eps
        hi = np.log(p_t * 0.999)
        lo = hi - 0.7
        while f(lo) < 0:                      # step down until the area ratio is passed
            hi, lo = lo, lo - 0.7
            if lo < np.log(p_t) - 25:
                raise ValueError(f"frozen expansion cannot reach area ratio {eps:g}")
        pe = float(np.exp(brentq(f, lo, hi, xtol=1e-10)))
    T_e, u_e, G_e = gas.state(pe)
    eps_out = G_t / G_e
    thrust_per_mdot = u_e + pe * 1e5 / G_e            # vacuum: u_e + p_e A_e / mdot
    cf_vac = thrust_per_mdot * G_t / (pc * 1e5)
    g_e = gas.gamma(T_e)
    Me = u_e / np.sqrt(g_e * gas.R * T_e)
    return NozzleState(cf_vac=float(cf_vac), pe_over_pc=pe / pc, exit_mach=float(Me),
                       gamma_exit=float(g_e), source=""), float(eps_out)


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _CardInfo:
    species: str
    t_K: float
    phase: str


@dataclass(frozen=True)
class NasaCeaModel:
    fuel: ReactantState
    ox: ReactantState
    nozzle_flow: str = "single_gamma"
    eps_hint: float = 3.0
    source: str = "nasa_cea"
    note: str = ""                       # e.g. why this backend replaced rocketcea
    card_info: dict = None               # type: ignore[assignment]

    @property
    def ox_state(self) -> str:
        return self.ox.describe()

    @property
    def fuel_state(self) -> str:
        return self.fuel.describe()

    @property
    def of_range(self) -> tuple[float, float]:
        return 0.5, 12.0

    def _key(self) -> tuple:
        return (self.fuel.species, round(self.fuel.h_J_kg, 3),
                self.ox.species, round(self.ox.h_J_kg, 3))

    def _run(self, of: float, pc: float, **kw) -> _Run:
        return _eq_run(*self._key(), round(float(of), 9), round(float(pc), 9), **kw)

    def _frozen(self, of: float, pc: float, at_throat: bool):
        return _frozen_throat(*self._key(), round(float(of), 9), round(float(pc), 9), at_throat)

    def at(self, of: float, pc_bar: float | None = None) -> CombustionResult:
        pc = pc_bar or 25.0
        run = self._run(of, pc)
        if self.nozzle_flow == "frozen":
            # composition frozen at the chamber: matching (lower) c*, so mdot,
            # CF and Isp stay mutually consistent
            _, _, G_t = self._frozen(of, pc, False)
            cstar = pc * 1e5 / G_t
        else:
            cstar = run.cstar
        mw = float(run.M[0])
        return CombustionResult(
            cstar_ideal_m_s=float(cstar), tc_K=float(run.T[0]), gamma=float(run.gamma_s[0]),
            mw_kg_kmol=mw, R_specific=_R_UNIVERSAL / mw, source=self.source,
            ox_state=self.ox_state, fuel_state=self.fuel_state,
            nozzle_flow=self.nozzle_flow,
        )

    def _nozzle_flow(self, of: float, pc: float, flow: str, eps: Optional[float] = None,
                     pe: Optional[float] = None) -> tuple[NozzleState, float]:
        if flow == "equilibrium":
            run = (self._run(of, pc, supar=(round(float(eps), 9),)) if pe is None
                   else self._run(of, pc, pi_p=(round(pc / pe, 9),)))
            ns = NozzleState(cf_vac=float(run.isp_vac[-1] / run.cstar),
                             pe_over_pc=float(run.P[-1] / run.P[0]),
                             exit_mach=float(run.mach[-1]), gamma_exit=float(run.gamma_s[-1]),
                             source="cea_equilibrium")
            return ns, float(run.ae_at[-1])
        gas, p_t, G_t = self._frozen(of, pc, flow == "frozen_at_throat")
        ns, e = _frozen_exit(gas, p_t, G_t, pc, eps=eps, pe=pe)
        return NozzleState(cf_vac=ns.cf_vac, pe_over_pc=ns.pe_over_pc, exit_mach=ns.exit_mach,
                           gamma_exit=ns.gamma_exit, source=f"cea_{flow}"), e

    def nozzle(self, of: float, pc_bar: float, eps: float) -> NozzleState:
        from .combustion import single_gamma_nozzle
        if self.nozzle_flow == "single_gamma":
            return single_gamma_nozzle(eps, self.at(of, pc_bar).gamma)
        return self._nozzle_flow(of, pc_bar, self.nozzle_flow, eps=eps)[0]

    def eps_for_pe(self, of: float, pc_bar: float, pe_bar: float
                   ) -> tuple[float, NozzleState]:
        from .combustion import check_supersonic_exit, single_gamma_eps_for_pe, single_gamma_nozzle
        g = self.at(of, pc_bar).gamma
        check_supersonic_exit(pc_bar * 1e5, pe_bar * 1e5, g)
        if self.nozzle_flow == "single_gamma":
            eps = single_gamma_eps_for_pe(pc_bar / pe_bar, g)
            return eps, single_gamma_nozzle(eps, g)
        ns, eps = self._nozzle_flow(of, pc_bar, self.nozzle_flow, pe=pe_bar)
        return eps, ns

    def transport(self, of: float, pc_bar: float | None = None) -> dict:
        """Chamber transport properties, frozen and equilibrium basis (SI)."""
        run = self._run(of, pc_bar or 25.0)
        return {
            "cp_frozen_J_kgK": float(run.cp_fr[0]), "mu_Pa_s": float(run.mu[0]),
            "k_frozen_W_mK": float(run.k_fr[0]), "pr_frozen": float(run.pr_fr[0]),
            "cp_eq_J_kgK": float(run.cp_eq[0]), "k_eq_W_mK": float(run.k_eq[0]),
            "pr_eq": float(run.pr_eq[0]), "mu_throat_Pa_s": float(run.mu[1]),
        }

    def reference(self, of: float, pc_bar: float, eps: float) -> dict:
        """Ideal vacuum Isp [s] of every nozzle-flow model at this point."""
        from .combustion import single_gamma_nozzle
        run = self._run(of, pc_bar)
        out = {"single_gamma": single_gamma_nozzle(eps, float(run.gamma_s[0])).cf_vac
               * run.cstar / _G0}
        for flow in ("equilibrium", "frozen", "frozen_at_throat"):
            ns, _ = self._nozzle_flow(of, pc_bar, flow, eps=eps)
            if flow == "frozen":
                _, _, G_t = self._frozen(of, pc_bar, False)
                cstar = pc_bar * 1e5 / G_t
            else:
                cstar = run.cstar
            out[flow] = ns.cf_vac * cstar / _G0
        return out


def available() -> bool:
    try:
        import cea  # noqa: F401
    except ImportError:
        return False
    return True


def build_nasa_model(prop, comb, *, ox_temp_K=None, fuel_temp_K=None,
                     pc_hint_bar: float = 25.0, note: str = "") -> NasaCeaModel:
    """NasaCeaModel from the propellant + combustion config (see module doc)."""
    if not available():
        raise RuntimeError(
            "backend='cea' needs the NASA CEA package — pip install cea (Python >= 3.11)")
    ox_spec, ox_forced = resolve_propellant(prop.cea_oxidizer, prop.oxidizer)
    fu_spec, fu_forced = resolve_propellant(prop.cea_fuel, prop.fuel)
    p_hint = pc_hint_bar * 1e5
    if comb.use_delivery_temperatures:
        T_o = round(float(ox_temp_K if ox_temp_K is not None else prop.ox_temp_K), 1)
        T_f = round(float(fuel_temp_K if fuel_temp_K is not None else prop.fuel_temp_K), 1)
        ox = reactant_state(ox_spec, T_o, prop.ox_phase, p_hint)
        fu = reactant_state(fu_spec, T_f, prop.fuel_phase, p_hint)
        info = {}
    else:
        ox = reactant_state(ox_spec, None, ox_forced, p_hint)
        fu = reactant_state(fu_spec, None, fu_forced, p_hint)
        info = {"oxidizer": _CardInfo(ox.species, ox.t_K, ox.phase),
                "fuel": _CardInfo(fu.species, fu.t_K, fu.phase)}
    return NasaCeaModel(fuel=fu, ox=ox, nozzle_flow=comb.nozzle_flow, note=note,
                        card_info=info)
