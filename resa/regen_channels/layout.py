"""Channel layout: turns contour + YAML profiles into per-station geometry.

Conventions
-----------
* beta(x): helix angle from the AXIAL direction. 0 = straight channel.
* Channel width is measured perpendicular to the channel path at the
  width-reference radius (mid-height by default):
      pitch_perp = 2*pi*r_ref/N * cos(beta)
      w = pitch_perp - t_rib            (fixed rib)  or
      t_rib = profile, w follows        (variable rib)
* Wrap angle: d(theta) = tan(beta) * ds_meridian / r_ref
* Channel path length: dl = ds_meridian / cos(beta)
"""
from __future__ import annotations

import numpy as np

from .config import RegenConfig
from .contour import Contour
from .profiles import Profile1D


class ChannelLayout:
    def __init__(self, contour: Contour, cfg: RegenConfig):
        self.contour = contour
        self.cfg = cfg
        ch = cfg.channels
        self.N = ch.count

        x0 = contour.x_min if ch.start_x is None else max(ch.start_x, contour.x_min)
        x1 = contour.x_max if ch.stop_x is None else min(ch.stop_x, contour.x_max)
        if x1 <= x0:
            raise ValueError("channels.stop_x must exceed channels.start_x")
        n = cfg.geometry.n_stations
        self.x = np.linspace(x0, x1, n)

        # contour quantities ------------------------------------------------
        self.r = contour.r(self.x)
        self.drdx = contour.drdx(self.x)
        self.phi_wall = np.arctan(self.drdx)              # meridian slope
        dsdx = np.sqrt(1.0 + self.drdx ** 2)
        self.ds = np.gradient(self.x) * dsdx              # meridian per stat.
        self.s = np.concatenate(([0.0], np.cumsum(
            0.5 * (dsdx[1:] + dsdx[:-1]) * np.diff(self.x))))

        # profiles -----------------------------------------------------------
        self.t_wall = Profile1D(ch.inner_wall_thickness, "inner_wall")(self.x)
        self.h = Profile1D(ch.height, "height")(self.x)
        beta_prof = Profile1D({"points": ch.helix.profile,
                               "interp": ch.helix.interp}
                              if isinstance(ch.helix.profile, list)
                              else ch.helix.profile, "helix")
        sign = 1.0 if ch.helix.handedness == "right" else -1.0
        self.beta = sign * np.radians(beta_prof(self.x))
        self.t_rib = Profile1D(ch.rib.width, "rib_width")(self.x)

        # width / hydraulics ---------------------------------------------------
        if cfg.geometry.width_reference == "mid_height":
            self.r_ref = self.r + self.t_wall + 0.5 * self.h
        else:
            self.r_ref = self.r + self.t_wall
        cosb = np.cos(self.beta)
        self.pitch_perp = 2.0 * np.pi * self.r_ref * cosb / self.N
        self.w = self.pitch_perp - self.t_rib
        if np.any(self.w < ch.min_channel_width):
            i = int(np.argmin(self.w))
            raise ValueError(
                f"Channel width {self.w[i]*1e3:.2f} mm at x={self.x[i]*1e3:.1f} mm "
                f"is below min_channel_width ({ch.min_channel_width*1e3:.2f} mm). "
                f"Reduce count/rib width or add helix angle.")

        self.A = self.w * self.h                            # flow area
        self.Dh = 2.0 * self.w * self.h / (self.w + self.h)
        self.dl = self.ds / cosb                            # channel path
        self.l = np.concatenate(([0.0], np.cumsum(
            0.5 * (1.0 / cosb[1:] + 1.0 / cosb[:-1]) *
            np.diff(self.s))))

        # wrap angle ----------------------------------------------------------
        integrand = np.tan(self.beta) / self.r_ref
        dth = 0.5 * (integrand[1:] + integrand[:-1]) * np.diff(self.s)
        self.theta = np.concatenate(([0.0], np.cumsum(dth)))

        # hot-gas side surface per channel per station -------------------------
        self.dA_hot = (2.0 * np.pi * self.r / self.N) * self.ds

        # helix curvature radius (helix on local radius r_ref):
        # kappa = sin^2(beta)/r_ref  -> R_c = r_ref / sin^2(beta)
        s2 = np.sin(self.beta) ** 2
        with np.errstate(divide="ignore"):
            self.R_curve = np.where(s2 > 1e-9, self.r_ref / np.maximum(s2, 1e-9),
                                    np.inf)

        # full-contour throat (for Bartz / area ratio) ---------------------------
        self.x_throat, self.r_throat = contour.throat()
        self.A_throat = np.pi * self.r_throat ** 2

    # ------------------------------------------------------------------
    def coverage_fraction(self):
        """Hot-wall fraction covered by channel footprint (vs. ribs)."""
        return self.w / np.maximum(self.pitch_perp, 1e-12)

    def to_dataframe(self):
        import pandas as pd
        return pd.DataFrame({
            "x_m": self.x, "r_m": self.r, "s_m": self.s, "l_channel_m": self.l,
            "beta_deg": np.degrees(self.beta), "theta_wrap_deg": np.degrees(self.theta),
            "height_m": self.h, "width_m": self.w, "rib_m": self.t_rib,
            "wall_m": self.t_wall, "area_m2": self.A, "Dh_m": self.Dh,
            "pitch_perp_m": self.pitch_perp, "R_curve_m": self.R_curve,
        })
