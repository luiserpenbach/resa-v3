"""Axial profiles: every channel property (height, rib width, helix angle, wall
thickness) is a Profile1D — either a constant scalar or breakpoints vs. axial
position x, with selectable interpolation. This is what makes straight /
spiral / switching layouts and variable height/rib purely a YAML concern.
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator, interp1d


class Profile1D:
    """A scalar property defined along the engine axis.

    YAML forms accepted:
        height: 2.0e-3                          # constant
        height: [[0.0, 3.0e-3], [0.21, 1.5e-3]] # breakpoints, pchip default
        height: {points: [[...]], interp: linear}
    Outside the breakpoint range the profile is held constant (clamped).
    """

    def __init__(self, spec, name: str = "profile", scale: float = 1.0):
        self.name = name
        if isinstance(spec, (int, float)):
            self._const = float(spec) * scale
            self._fn = None
            self.x_pts = None
        else:
            if isinstance(spec, dict):
                pts = spec["points"]
                interp = spec.get("interp", "pchip")
            else:
                pts = spec
                interp = "pchip"
            pts = np.asarray(pts, dtype=float)
            if pts.ndim != 2 or pts.shape[1] != 2:
                raise ValueError(f"{name}: breakpoints must be [[x, value], ...]")
            order = np.argsort(pts[:, 0])
            x, v = pts[order, 0], pts[order, 1] * scale
            self.x_pts, self.v_pts = x, v
            self._const = None
            if len(x) == 1:
                self._const = float(v[0])
                self._fn = None
            elif interp == "linear":
                self._fn = interp1d(x, v, bounds_error=False,
                                    fill_value=(v[0], v[-1]))
            elif interp == "pchip":
                itp = PchipInterpolator(x, v, extrapolate=False)

                def fn(q, itp=itp, x=x, v=v):
                    q = np.asarray(q, dtype=float)
                    out = itp(np.clip(q, x[0], x[-1]))
                    return out
                self._fn = fn
            else:
                raise ValueError(f"{name}: unknown interp '{interp}'")

    def __call__(self, x):
        x = np.asarray(x, dtype=float)
        if self._const is not None:
            return np.full_like(x, self._const, dtype=float)
        return np.asarray(self._fn(x), dtype=float)

    @property
    def is_constant(self) -> bool:
        return self._const is not None
