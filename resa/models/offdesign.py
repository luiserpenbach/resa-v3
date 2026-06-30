"""Off-design / throttle analysis: map evaluate_point over ranges.

All sweeps run at FIXED geometry (the nominal At, eps) — exactly what happens
on the test stand. Because every point goes through the same kernel as analyze
mode, sweep physics can never diverge from single-point physics.

Sweeps are defined relative to the nominal point:
  ox_throttle : mdot_ox = fraction × nominal, mdot_fuel = const (E2 style)
  of_sweep    : O/F varies at constant TOTAL mdot
  envelope    : 2-D grid, total-mdot throttle fraction × O/F
"""
from __future__ import annotations

import numpy as np

from ..config.schema import OffDesignConfig
from ..results import EnvelopeResult, OffDesignResult, SweepResult, ThrustChamberResult
from .thrust_chamber import evaluate_point


def _collect(kind: str, points: list[dict]) -> SweepResult:
    col = lambda k: np.array([p[k] for p in points])
    return SweepResult(
        kind=kind,
        mdot_ox_kg_s=col("mdot_ox"), mdot_fuel_kg_s=col("mdot_fuel"),
        mdot_total_kg_s=col("mdot"), of=col("of"),
        pc_bar=col("pc_bar"), thrust_N=col("thrust_N"), isp_s=col("isp_s"),
        cf=col("cf"), cstar_eff_m_s=col("cstar_eff_m_s"), pe_bar=col("pe_bar"),
        separated=col("separated").astype(bool),
    )


def run(
    od: OffDesignConfig,
    tc: ThrustChamberResult,
    model,
    p_amb_bar: float,
    eta_cstar: float | None = None,
) -> OffDesignResult:
    """eta_cstar overrides tc.eta_cstar (used for uncertainty band re-runs:
    same commanded flows and geometry, different combustion efficiency)."""
    at, eps = tc.throat_area_m2, tc.eps
    eta = eta_cstar if eta_cstar is not None else tc.eta_cstar
    pc0 = tc.pc_bar
    of_lo, of_hi = model.of_range
    notes: list[str] = []
    ev = lambda mox, mf: evaluate_point(
        at, eps, mox, mf, model, eta, p_amb_bar, pc_guess_bar=pc0,
        eta_cf=tc.eta_cf,
    )

    def _of_ok(of: float) -> bool:
        return of_lo - 1e-9 <= of <= of_hi + 1e-9

    ox_sweep = of_sweep = env = None

    if od.ox_throttle is not None:
        s = od.ox_throttle
        fracs = np.linspace(*s.ox_fraction, s.n)
        valid = [f for f in fracs
                 if _of_ok(f * tc.mdot_ox_kg_s / tc.mdot_fuel_kg_s)]
        if len(valid) < len(fracs):
            notes.append(
                f"ox_throttle truncated to O/F table [{of_lo:g}, {of_hi:g}]: "
                f"{len(fracs)-len(valid)} of {len(fracs)} points dropped "
                f"(extend combustion table to cover deeper throttle)"
            )
        pts = [ev(f * tc.mdot_ox_kg_s, tc.mdot_fuel_kg_s) for f in valid]
        ox_sweep = _collect("ox_throttle", pts)

    if od.of_sweep is not None:
        s = od.of_sweep
        lo = max(s.of_range[0], of_lo)
        hi = min(s.of_range[1], of_hi)
        if (lo, hi) != tuple(s.of_range):
            notes.append(f"of_sweep clipped to O/F table: [{lo:g}, {hi:g}]")
        ofs = np.linspace(lo, hi, s.n)
        mdot = tc.mdot_total_kg_s
        pts = [ev(mdot * o / (1 + o), mdot / (1 + o)) for o in ofs]
        of_sweep = _collect("of_sweep", pts)

    if od.envelope is not None:
        s = od.envelope
        tf = np.linspace(*s.throttle_fraction, s.n[0])
        lo = max(s.of_range[0], of_lo)
        hi = min(s.of_range[1], of_hi)
        if (lo, hi) != tuple(s.of_range):
            notes.append(f"envelope clipped to O/F table: [{lo:g}, {hi:g}]")
        ofs = np.linspace(lo, hi, s.n[1])
        shape = (len(ofs), len(tf))
        pc = np.zeros(shape); F = np.zeros(shape)
        isp = np.zeros(shape); sep = np.zeros(shape, dtype=bool)
        for i, o in enumerate(ofs):
            for j, f in enumerate(tf):
                mdot = f * tc.mdot_total_kg_s
                p = ev(mdot * o / (1 + o), mdot / (1 + o))
                pc[i, j], F[i, j] = p["pc_bar"], p["thrust_N"]
                isp[i, j], sep[i, j] = p["isp_s"], p["separated"]
        env = EnvelopeResult(throttle_frac=tf, of=ofs, pc_bar=pc,
                             thrust_N=F, isp_s=isp, separated=sep)

    return OffDesignResult(ox_throttle=ox_sweep, of_sweep=of_sweep,
                           envelope=env, notes=tuple(notes))
