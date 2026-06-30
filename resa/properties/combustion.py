"""Combustion model: properties as a function of O/F (and Pc for rocketcea).

build_model() returns a CombustionModel with `.at(of, pc_bar)` so downstream
code (sizing, O/F optimization, throttle sweeps) is backend-agnostic.

backend='table'    : interpolate the team's CEA table over O/F. A single-point
                     table works for fixed-O/F design but NOT for optimization
                     or sweeps (raises with a clear message).
backend='rocketcea': live CEA per call (needs fortran toolchain).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ..config.schema import CombustionConfig, PropellantConfig
from ..results import CombustionResult

_R_UNIVERSAL = 8314.462618  # J/(kmol·K)


@dataclass(frozen=True)
class TableModel:
    of_grid: np.ndarray | None       # None -> single point
    cstar: np.ndarray
    tc: np.ndarray
    gamma: np.ndarray
    mw: np.ndarray
    source: str = "table"

    @property
    def of_range(self) -> tuple[float, float]:
        if self.of_grid is None:
            raise ValueError(
                "combustion table is a single point — O/F optimization and "
                "sweeps need a table over O/F (give `of:` as a list)"
            )
        return float(self.of_grid[0]), float(self.of_grid[-1])

    def at(self, of: float, pc_bar: float | None = None) -> CombustionResult:
        if self.of_grid is None:
            vals = (self.cstar[0], self.tc[0], self.gamma[0], self.mw[0])
        else:
            lo, hi = self.of_range
            if not (lo - 1e-9 <= of <= hi + 1e-9):
                raise ValueError(
                    f"O/F={of:.3f} outside combustion table [{lo}, {hi}] — "
                    "extend the table (no extrapolation, accuracy first)"
                )
            vals = tuple(
                float(np.interp(of, self.of_grid, a))
                for a in (self.cstar, self.tc, self.gamma, self.mw)
            )
        cstar, tc, g, mw = vals
        return CombustionResult(
            cstar_ideal_m_s=cstar, tc_K=tc, gamma=g, mw_kg_kmol=mw,
            R_specific=_R_UNIVERSAL / mw, source=self.source,
        )


@lru_cache(maxsize=16)
def _cea_obj(ox: str, fuel: str):
    from rocketcea.cea_obj_w_units import CEA_Obj  # noqa: deferred import
    return CEA_Obj(oxName=ox, fuelName=fuel)


@dataclass(frozen=True)
class CeaModel:
    ox: str
    fuel: str
    eps_hint: float = 3.0
    source: str = "rocketcea"

    @property
    def of_range(self) -> tuple[float, float]:
        return 0.5, 12.0

    def at(self, of: float, pc_bar: float | None = None) -> CombustionResult:
        pc_psia = (pc_bar or 25.0) * 14.5038
        cea = _cea_obj(self.ox, self.fuel)
        cstar = cea.get_Cstar(Pc=pc_psia, MR=of) * 0.3048
        tc = cea.get_Tcomb(Pc=pc_psia, MR=of) * 5.0 / 9.0
        mw, g = cea.get_Chamber_MolWt_gamma(Pc=pc_psia, MR=of, eps=self.eps_hint)
        return CombustionResult(
            cstar_ideal_m_s=cstar, tc_K=tc, gamma=g, mw_kg_kmol=mw,
            R_specific=_R_UNIVERSAL / mw, source=self.source,
        )


CombustionModel = TableModel | CeaModel


def build_model(prop: PropellantConfig, comb: CombustionConfig) -> CombustionModel:
    if comb.backend == "table":
        t = comb.table
        as_arr = lambda v: np.atleast_1d(np.asarray(v, dtype=float))
        return TableModel(
            of_grid=None if t.of is None else np.asarray(t.of, dtype=float),
            cstar=as_arr(t.cstar_m_s), tc=as_arr(t.tc_K),
            gamma=as_arr(t.gamma), mw=as_arr(t.mw_kg_kmol),
        )
    if comb.backend == "rocketcea":
        try:
            import rocketcea  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "backend='rocketcea' needs rocketcea installed (fortran "
                "toolchain). Use backend='table' otherwise."
            ) from e
        return CeaModel(ox=prop.cea_oxidizer or prop.oxidizer,
                        fuel=prop.cea_fuel or prop.fuel)
    raise ValueError(f"unknown combustion backend {comb.backend!r}")
