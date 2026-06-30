"""Thin CoolProp wrapper with a pressure-keyed memoization layer.

Background: a naive solver can issue hundreds of identical PropsSI calls per
march step. Round p to a small grid and memoize → large speedups with
negligible accuracy loss for transport/EOS lookups.
"""
from __future__ import annotations

from functools import lru_cache

from CoolProp.CoolProp import PropsSI

# Round pressure to this many Pa before caching (1 kPa grid → <0.01% error)
_P_GRID = 1_000.0
# Round temperature to this many K
_T_GRID = 0.1


@lru_cache(maxsize=200_000)
def _cached(prop: str, T_q: float, p_q: float, fluid: str) -> float:
    return PropsSI(prop, "T", T_q, "P", p_q, fluid)


_RHO_GRID = 0.5  # kg/m³


@lru_cache(maxsize=200_000)
def _cached_dr(prop: str, T_q: float, rho_q: float, fluid: str) -> float:
    return PropsSI(prop, "T", T_q, "D", rho_q, fluid)


def prop(name: str, T: float, p: float, fluid: str) -> float:
    """PropsSI(name, 'T', T, 'P', p, fluid) with quantized caching.

    Parameters
    ----------
    name : CoolProp output, e.g. 'D' (density), 'C' (cp), 'V' (viscosity),
           'L' (conductivity), 'H' (enthalpy), 'PRANDTL'.
    """
    T_q = round(T / _T_GRID) * _T_GRID
    p_q = round(p / _P_GRID) * _P_GRID
    return _cached(name, T_q, p_q, fluid)


def density(T: float, p: float, fluid: str) -> float:
    return prop("D", T, p, fluid)


def prop_dr(name: str, T: float, rho: float, fluid: str) -> float:
    """PropsSI(name, 'T', T, 'D', rho, fluid) with quantized caching."""
    T_q = round(T / _T_GRID) * _T_GRID
    rho_q = round(rho / _RHO_GRID) * _RHO_GRID
    return _cached_dr(name, T_q, rho_q, fluid)


def transport(T: float, p: float, fluid: str) -> dict[str, float]:
    """Bundle the four properties a heat-transfer correlation needs."""
    return {
        "rho": prop("D", T, p, fluid),
        "cp": prop("C", T, p, fluid),
        "mu": prop("V", T, p, fluid),
        "k": prop("L", T, p, fluid),
    }


def cache_info() -> str:
    return str(_cached.cache_info())
