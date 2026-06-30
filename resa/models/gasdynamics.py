"""Quasi-1D isentropic relations. Single home for area<->Mach<->pressure.

Imported by thrust_chamber (sizing) and contour (station Mach distribution) so
the relations exist in exactly one place. Pure functions, no state.
Refs: Sutton, *Rocket Propulsion Elements*, 9th ed., ch. 3.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq


def area_ratio_from_mach(M: float, g: float) -> float:
    """A/A* for isentropic flow (Sutton 3-14)."""
    return (1.0 / M) * ((2.0 / (g + 1.0)) * (1.0 + 0.5 * (g - 1.0) * M * M)) ** (
        (g + 1.0) / (2.0 * (g - 1.0))
    )


def mach_from_pressure_ratio(pc_over_p: float, g: float) -> float:
    """Mach from stagnation/static pressure ratio (isentropic)."""
    return np.sqrt((2.0 / (g - 1.0)) * (pc_over_p ** ((g - 1.0) / g) - 1.0))


def mach_from_area_ratio(eps: float, g: float, supersonic: bool) -> float:
    """Invert A/A* = eps on the chosen branch.

    supersonic=False → subsonic root (chamber / convergent side, M<1)
    supersonic=True  → supersonic root (divergent side, M>1)
    """
    if eps <= 1.0 + 1e-12:
        return 1.0
    f = lambda M: area_ratio_from_mach(M, g) - eps
    if supersonic:
        return brentq(f, 1.0 + 1e-9, 60.0)
    return brentq(f, 1e-6, 1.0 - 1e-9)


def pressure_ratio_from_mach(M: float, g: float) -> float:
    """p/pc (static over stagnation)."""
    return (1.0 + 0.5 * (g - 1.0) * M * M) ** (-g / (g - 1.0))


def temperature_ratio_from_mach(M: float, g: float) -> float:
    """T/Tc (static over stagnation)."""
    return 1.0 / (1.0 + 0.5 * (g - 1.0) * M * M)
