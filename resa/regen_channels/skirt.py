"""Radiation-cooled nozzle extension (skirt) downstream of the regen channels.

At every uncooled station the wall settles where Bartz convection from the
gas equals grey-body radiation from the outer surface to the environment:

    h_g(T_w) (T_aw - T_w) = emissivity * sigma * (T_w^4 - T_env^4)

Conduction along the skirt and radiation from the inner face (which mostly
sees other hot wall or leaves through the exit) are neglected, so this is the
classic first-order design estimate for thin refractory skirts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .hotgas import HotGas

SIGMA_SB = 5.670374419e-8


def solve_radiation_skirt(hot: HotGas, x: np.ndarray, r: np.ndarray,
                          x_throat: float, emissivity: float,
                          T_env_K: float) -> pd.DataFrame:
    """Per-station radiation-equilibrium wall temperature for stations x, r."""
    x = np.asarray(x, float)
    r = np.asarray(r, float)
    M = hot.mach_profile(x, r, x_throat)
    T_aw = hot.t_aw(M)
    eps = (r / np.sqrt(hot.At / np.pi)) ** 2
    T_w, q, hg = np.empty_like(x), np.empty_like(x), np.empty_like(x)
    for i in range(len(x)):
        def f(Tw, i=i):
            return (hot.h_g(M[i], eps[i], Tw) * (T_aw[i] - Tw)
                    - emissivity * SIGMA_SB * (Tw ** 4 - T_env_K ** 4))
        lo, hi = max(T_env_K, 1.0), T_aw[i] - 1e-3
        T_w[i] = brentq(f, lo, hi) if f(lo) > 0 > f(hi) else (hi if f(hi) > 0 else lo)
        hg[i] = hot.h_g(M[i], eps[i], T_w[i])
        q[i] = hg[i] * (T_aw[i] - T_w[i])
    ds = np.gradient(x) * np.sqrt(1.0 + np.gradient(r, x) ** 2)
    dA = 2.0 * np.pi * r * ds
    df = pd.DataFrame(dict(x_m=x, r_m=r, area_ratio=eps, mach=M, T_aw_K=T_aw,
                           h_g=hg, T_wall_K=T_w, q_W_m2=q, dA_m2=dA))
    df.attrs.update(
        T_wall_max_K=float(T_w.max()), T_wall_exit_K=float(T_w[-1]),
        Q_radiated_kW=float(np.sum(q * dA)) / 1e3,
        emissivity=emissivity, T_env_K=T_env_K,
        x_start_m=float(x[0]), x_end_m=float(x[-1]),
    )
    return df
