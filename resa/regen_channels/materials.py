"""Wall material database: conductivity, elastic constants, yield strength and
a service-temperature limit per alloy.

Values are INDICATIVE engineering numbers from public data sheets (rounded,
typical heat treatments) meant for margin screening. Override per material
data sheet through ``solver.wall`` (yield_MPa, E_GPa, alpha_1_K, poisson,
conductivity, max_wall_temp_K) for anything load-bearing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import numpy as np

Points = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Material:
    key: str
    name: str
    k_points: Points            # (T [K], k [W/m/K])
    E_GPa: float
    alpha_1_K: float            # mean CTE
    poisson: float
    yield_points: Points        # (T [K], sigma_y [MPa])
    max_service_T_K: float      # hot-wall screening limit
    note: str = ""

    def k(self, T: float) -> float:
        t, k = zip(*self.k_points)
        return float(np.interp(T, t, k))

    def yield_MPa(self, T: float) -> float:
        t, s = zip(*self.yield_points)
        return float(np.interp(T, t, s))


MATERIALS: dict[str, Material] = {
    "in718": Material(
        "in718", "Inconel 718",
        k_points=((300, 11.4), (500, 14.0), (700, 16.6), (900, 19.2), (1100, 21.8), (1300, 24.4)),
        E_GPa=200.0, alpha_1_K=13.0e-6, poisson=0.29,
        yield_points=((300, 1030), (600, 980), (800, 900), (900, 760), (1000, 500), (1100, 250), (1200, 120)),
        max_service_T_K=1000.0,
        note="precipitation-hardened Ni superalloy; strength collapses above ~950 K",
    ),
    "in625": Material(
        "in625", "Inconel 625",
        k_points=((300, 9.8), (500, 12.9), (700, 16.0), (900, 19.1), (1100, 22.2), (1300, 25.0)),
        E_GPa=205.0, alpha_1_K=12.8e-6, poisson=0.31,
        yield_points=((300, 415), (600, 360), (800, 330), (1000, 270), (1100, 180), (1200, 90)),
        max_service_T_K=1100.0,
        note="solid-solution Ni superalloy; oxidation-resistant, lower strength than 718",
    ),
    "ss316l": Material(
        "ss316l", "Stainless 316L",
        k_points=((300, 13.4), (500, 16.4), (700, 19.4), (900, 22.4), (1100, 25.4)),
        E_GPa=193.0, alpha_1_K=16.0e-6, poisson=0.30,
        yield_points=((300, 240), (600, 150), (800, 120), (1000, 90), (1100, 60)),
        max_service_T_K=1050.0,
    ),
    "cucrzr": Material(
        "cucrzr", "CuCrZr",
        k_points=((300, 320), (500, 315), (700, 300), (900, 285)),
        E_GPa=128.0, alpha_1_K=17.0e-6, poisson=0.33,
        yield_points=((300, 300), (500, 270), (600, 230), (700, 170), (800, 110), (900, 50)),
        max_service_T_K=800.0,
        note="precipitation-hardened copper; over-ages above ~750 K",
    ),
    "grcop42": Material(
        "grcop42", "GRCop-42",
        k_points=((300, 300), (500, 295), (700, 290), (900, 280), (1100, 270)),
        E_GPa=118.0, alpha_1_K=17.5e-6, poisson=0.34,
        yield_points=((300, 220), (600, 190), (800, 160), (900, 140), (1000, 110), (1100, 70)),
        max_service_T_K=1000.0,
        note="Cu-Cr-Nb (NASA); retains strength to ~1000 K",
    ),
    "c103": Material(
        "c103", "Nb C-103",
        k_points=((300, 42), (700, 46), (1100, 50), (1500, 54), (1800, 57)),
        E_GPa=90.0, alpha_1_K=8.3e-6, poisson=0.35,
        yield_points=((300, 300), (800, 220), (1100, 170), (1300, 140), (1500, 100), (1700, 60)),
        max_service_T_K=1600.0,
        note="niobium alloy for radiation-cooled skirts; needs silicide coating",
    ),
    "copper": Material(
        "copper", "OFHC copper",
        k_points=((300, 390), (500, 380), (700, 365), (900, 350)),
        E_GPa=115.0, alpha_1_K=17.0e-6, poisson=0.34,
        yield_points=((300, 70), (500, 55), (600, 45), (700, 35), (800, 25)),
        max_service_T_K=700.0,
    ),
}

_ALIASES = {
    "in718": "in718", "inconel718": "in718", "alloy718": "in718", "718": "in718",
    "in625": "in625", "inconel625": "in625", "alloy625": "in625", "625": "in625",
    "ss316l": "ss316l", "316l": "ss316l", "stainless316l": "ss316l", "aisi316l": "ss316l", "ss316": "ss316l",
    "cucrzr": "cucrzr", "c18150": "cucrzr", "cucr1zr": "cucrzr",
    "grcop42": "grcop42", "grcop": "grcop42", "grcop84": "grcop42",
    "c103": "c103", "nbc103": "c103", "niobium": "c103", "nb": "c103",
    "copper": "copper", "cu": "copper", "ofhc": "copper", "ofe": "copper", "oxygenfreecopper": "copper",
}

# legacy conductivity keyword accepted by WallCfg.conductivity
_CONDUCTIVITY_KEYS = {"inconel718": "in718"}


def normalize(name: str) -> str:
    return re.sub(r"[\s_\-()./]", "", name).lower()


def resolve(name: Optional[str]) -> Optional[Material]:
    """Material for a free-text name (case/space-insensitive); None if unknown."""
    if not name:
        return None
    key = normalize(name)
    key = _CONDUCTIVITY_KEYS.get(key, key)
    key = _ALIASES.get(key, key)
    return MATERIALS.get(key)
