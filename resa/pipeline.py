"""Pipeline: wires stages in explicit order. No magic, no hidden DAG engine.

Two modes (set by which config block exists):
  design  : operating_point -> size geometry from thrust/pc targets
  analyze : geometry + analyze_point -> specs from measured hardware + flows
Both produce the same EngineResult; provenance marks input vs calculated.
"""
from __future__ import annotations

import numpy as np

from .config.loader import load_config
from .config.schema import EngineConfig
from .models import contour, offdesign, thrust_chamber
from .properties import combustion
from .results import EngineResult, UncertaintyResult


def _checks(cfg: EngineConfig, tc, cont, *, pc_converged: bool = True) -> tuple:
    """Cheap physical sanity checks -> human-readable warnings."""
    w = []
    if not pc_converged:
        w.append(
            "chamber pressure fixed-point did not converge in 20 iterations "
            f"(final pc={tc.pc_bar:.3f} bar) — check mass flows and eta_c*"
        )
    if tc.separated:
        w.append(
            f"FLOW SEPARATION RISK at nominal: pe={tc.pe_bar:.2f} bar < "
            f"0.4·p_amb (Summerfield)"
        )
    c = cfg.cooling
    circ = 2 * np.pi * (tc.throat_radius_m + c.inner_wall_thickness_m)
    need = c.n_channels * (c.channel_width_m + c.rib_width_m)
    if need > circ:
        w.append(
            f"cooling channels do not fit throat circumference: "
            f"{c.n_channels}×(w+rib)={need*1e3:.1f} mm > {circ*1e3:.1f} mm"
        )
    if cont is not None and cont.chamber_length_m < cont.chamber_radius_m:
        w.append("chamber length < chamber radius — check L* / contraction ratio")
    if cont is not None:
        # L* feasibility: the convergent section alone may already exceed the
        # requested chamber volume (cylinder length clamps to 0 silently)
        i = np.argsort(cont.x_m)
        x, r = cont.x_m[i], cont.r_m[i]
        m = x <= 0
        vc_actual = np.trapezoid(np.pi * r[m] ** 2, x[m])
        vc_target = cfg.chamber.l_star_m * tc.throat_area_m2
        if vc_actual > 1.01 * vc_target:
            w.append(
                f"L*={cfg.chamber.l_star_m:g} m is unachievable: convergent "
                f"volume alone gives L*={vc_actual/tc.throat_area_m2:.3f} m "
                "(cylinder length clamped to 0) — raise L* or contraction ratio"
            )
    return tuple(w)


def run(cfg: EngineConfig) -> EngineResult:
    # 1. combustion model (c*, Tc, gamma as functions of O/F) ----------------
    model = combustion.build_model(cfg.propellants, cfg.combustion)

    # 2. nominal point: design sizing OR reverse analysis --------------------
    if cfg.mode == "design":
        tc = thrust_chamber.size(cfg.operating_point, model)
        p_amb = cfg.operating_point.p_amb_bar
    else:
        tc = thrust_chamber.analyze(cfg.geometry, cfg.analyze_point, model)
        p_amb = cfg.analyze_point.p_amb_bar

    comb = model.at(tc.of_ratio, pc_bar=tc.pc_bar)

    # 3. contour generation ---------------------------------------------------
    cont = contour.generate(tc, cfg.chamber, comb.gamma)

    # 4. off-design / throttle sweeps (same kernel, fixed geometry) -----------
    od = None
    if cfg.offdesign is not None:
        od = offdesign.run(cfg.offdesign, tc, model, p_amb)

    # 5. uncertainty: bounding re-runs at eta_cstar ± tol ----------------------
    unc = None
    point = cfg.operating_point if cfg.mode == "design" else cfg.analyze_point
    tol = point.eta_cstar_tol
    if tol is not None:
        def _at_eta(eta):
            if cfg.mode == "design":
                return thrust_chamber.size(
                    cfg.operating_point.model_copy(update={"eta_cstar": eta}),
                    model)
            return thrust_chamber.analyze(
                cfg.geometry,
                cfg.analyze_point.model_copy(update={"eta_cstar": eta}),
                model)
        tc_lo, tc_hi = _at_eta(point.eta_cstar - tol), _at_eta(point.eta_cstar + tol)
        od_lo = od_hi = None
        if cfg.offdesign is not None:
            od_lo = offdesign.run(cfg.offdesign, tc, model, p_amb,
                                  eta_cstar=point.eta_cstar - tol)
            od_hi = offdesign.run(cfg.offdesign, tc, model, p_amb,
                                  eta_cstar=point.eta_cstar + tol)
        unc = UncertaintyResult(eta_tol=tol, tc_lo=tc_lo, tc_hi=tc_hi,
                                od_lo=od_lo, od_hi=od_hi)

    return EngineResult(
        engine=cfg.engine, config_hash=cfg.config_hash, mode=cfg.mode,
        combustion=comb, thrust_chamber=tc, contour=cont, offdesign=od,
        uncertainty=unc,
        warnings=_checks(cfg, tc, cont, pc_converged=tc.pc_converged) + (od.notes if od else ()),
    )


def run_file(path: str) -> EngineResult:
    return run(load_config(path))
