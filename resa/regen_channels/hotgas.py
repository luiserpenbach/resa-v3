"""Hot-gas side: 1D isentropic Mach from area ratio + Bartz film coefficient.

Gas properties (Tc, gamma, M, mu, Pr, c*) come from the YAML — plug CEA
values in. A small-engine correction factor multiplies Bartz (default 0.75,
consistent with E2 throat heat-flux anchoring).
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

R_UNIV = 8314.462618


class HotGas:
    def __init__(self, cfg, A_throat: float, D_throat: float,
                 r_curv_throat: float):
        self.pc = cfg.pc_bar * 1e5
        self.Tc = cfg.tc_K
        self.g = cfg.gamma
        self.M_mol = cfg.mol_mass_kg_kmol
        self.R = R_UNIV / self.M_mol
        self.cp = self.g * self.R / (self.g - 1.0)
        self.mu = cfg.mu_pa_s
        self.Pr = cfg.pr if cfg.pr is not None else 4 * self.g / (9 * self.g - 5)
        self.cstar = cfg.c_star_m_s
        self.corr = cfg.bartz_correction
        self.At, self.Dt = A_throat, D_throat
        self.r_curv = max(r_curv_throat, 0.1 * D_throat)
        self.rec = self.Pr ** (1.0 / 3.0)        # turbulent recovery factor
        self.mdot = self.pc * self.At / self.cstar

    # ----------------------------------------------------------- mach -----
    def _area_ratio(self, M: float) -> float:
        g = self.g
        return (1.0 / M) * ((2.0 / (g + 1.0)) *
                            (1.0 + 0.5 * (g - 1.0) * M * M)) ** \
            ((g + 1.0) / (2.0 * (g - 1.0)))

    def mach(self, eps: float, supersonic: bool) -> float:
        eps = max(eps, 1.0 + 1e-9)
        if supersonic:
            return brentq(lambda M: self._area_ratio(M) - eps, 1.0 + 1e-9, 50.0)
        return brentq(lambda M: self._area_ratio(M) - eps, 1e-6, 1.0)

    def mach_profile(self, x: np.ndarray, r: np.ndarray, x_throat: float):
        eps = (r / np.sqrt(self.At / np.pi)) ** 2
        return np.array([self.mach(e, xi > x_throat)
                         for e, xi in zip(eps, x)])

    # ----------------------------------------------------------- bartz ----
    def t_aw(self, M: np.ndarray) -> np.ndarray:
        g = self.g
        return self.Tc * (1.0 + self.rec * 0.5 * (g - 1) * M * M) / \
            (1.0 + 0.5 * (g - 1) * M * M)

    def h_g(self, M: float, area_ratio: float, T_wall: float) -> float:
        g = self.g
        fM = 1.0 + 0.5 * (g - 1.0) * M * M
        sigma = 1.0 / ((0.5 * (T_wall / self.Tc) * fM + 0.5) ** 0.68
                       * fM ** 0.12)
        h = (0.026 / self.Dt ** 0.2
             * (self.mu ** 0.2 * self.cp / self.Pr ** 0.6)
             * (self.pc / self.cstar) ** 0.8
             * (self.Dt / self.r_curv) ** 0.1
             * (1.0 / area_ratio) ** 0.9
             * sigma)
        return self.corr * h
