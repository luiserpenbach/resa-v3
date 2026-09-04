"""Pipeline: wires stages in explicit order. No magic, no hidden DAG engine.

Two modes (set by which config block exists):
  design  : operating_point -> size geometry from thrust/pc targets
  analyze : geometry + analyze_point -> specs from measured hardware + flows
Both produce the same EngineResult; provenance marks input vs calculated.

Two optional fixed-point loops wrap the nominal point:
  * eta_cf_source: estimate  -> eta_cf from models/losses.py, re-sized
  * propellants.*_temp_source: regen_outlet -> the regen coolant outlet
    temperature feeds the propellant enthalpy (rocketcea delivery cards)
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from .config.loader import load_config
from .config.schema import EngineConfig
from .models import contour, film, losses, offdesign, thrust_chamber
from .properties import combustion
from .results import CouplingResult, EngineResult, NozzleReference, UncertaintyResult

_MAX_COUPLING_ITER = 8
_T_TOL_K = 0.5
_ETA_TOL = 2e-4
_KINETIC_PC_BAR = 15.0       # below this, recombination kinetics matter
_BAND_WARN = 0.02            # eq/frozen spread that earns a warning


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


def _cooling_block_check(cfg: EngineConfig, tc, comb, cont) -> tuple:
    """The `cooling` block only feeds the throat fit check; the regen block
    drives the solver. Flag disagreements so the report cannot mislead."""
    if cfg.regen is None or cont is None:
        return ()
    try:
        from .regen.integration import _build_contour, prepare_regen_config
        from .regen_channels.layout import ChannelLayout
        regen = prepare_regen_config(cfg.regen, tc, comb, cfg.chamber,
                                     film=cfg.film_cooling, propellants=cfg.propellants)
        lay = ChannelLayout(_build_contour(regen, cont), regen)
    except Exception as exc:  # layout errors surface from the regen run itself
        return (f"regen layout could not be built for the cooling-block check: {exc}",)
    i = int(np.argmin(np.abs(lay.x - lay.x_throat)))
    c = cfg.cooling
    diffs = []
    if lay.N != c.n_channels:
        diffs.append(f"channels {c.n_channels} vs {lay.N}")
    if abs(lay.w[i] - c.channel_width_m) > 0.2 * c.channel_width_m:
        diffs.append(f"throat width {c.channel_width_m*1e3:.2f} vs {lay.w[i]*1e3:.2f} mm")
    if abs(lay.h[i] - c.channel_height_m) > 0.2 * c.channel_height_m:
        diffs.append(f"height {c.channel_height_m*1e3:.2f} vs {lay.h[i]*1e3:.2f} mm")
    if abs(lay.t_wall[i] - c.inner_wall_thickness_m) > 0.2 * c.inner_wall_thickness_m:
        diffs.append(f"wall {c.inner_wall_thickness_m*1e3:.2f} vs {lay.t_wall[i]*1e3:.2f} mm")
    if diffs:
        return (
            "cooling block disagrees with the regen layout the solver uses ("
            + "; ".join(diffs) + ") — the cooling block only feeds the throat "
            "fit check; regen results follow the regen block",
        )
    return ()


def _combustion_state_warnings(cfg: EngineConfig, model) -> tuple:
    """Warn when CEA runs on its default propellant reference states while the
    config specifies clearly different delivery conditions."""
    if cfg.combustion.backend != "rocketcea" or cfg.combustion.use_delivery_temperatures:
        return ()
    info = getattr(model, "card_info", None) or {}
    pr = cfg.propellants
    out = []
    for side, T_cfg, phase_cfg in (("oxidizer", pr.ox_temp_K, pr.ox_phase),
                                   ("fuel", pr.fuel_temp_K, pr.fuel_phase)):
        ci = info.get(side)
        if ci is None:
            continue
        if abs(T_cfg - ci.t_K) > 30.0 or (phase_cfg and ci.phase not in ("unknown", phase_cfg)):
            out.append(
                f"combustion uses the CEA default {side} state {ci.species} at "
                f"{ci.t_K:.1f} K although propellants.{'ox' if side == 'oxidizer' else 'fuel'}"
                f"_temp_K = {T_cfg:.1f} K — set combustion.use_delivery_temperatures: true"
            )
    return tuple(out)


def _nozzle_reference(cfg: EngineConfig, model, tc) -> tuple:
    """(NozzleReference or None, warnings)."""
    ref = model.reference(tc.of_ratio, tc.pc_bar, tc.eps)
    if ref is None:
        return None, ()
    nr = NozzleReference(
        selected=cfg.combustion.nozzle_flow, eps=tc.eps,
        isp_vac_single_gamma_s=ref["single_gamma"],
        isp_vac_equilibrium_s=ref["equilibrium"],
        isp_vac_frozen_s=ref["frozen"],
        isp_vac_frozen_at_throat_s=ref["frozen_at_throat"],
    )
    w = []
    spread = nr.spread_fraction() or 0.0
    sg_vs_eq = ref["single_gamma"] / ref["equilibrium"] - 1.0
    if cfg.combustion.nozzle_flow == "single_gamma" and abs(sg_vs_eq) > _BAND_WARN:
        w.append(
            f"nozzle_flow=single_gamma: ideal vacuum Isp {ref['single_gamma']:.1f} s vs CEA "
            f"equilibrium {ref['equilibrium']:.1f} s ({sg_vs_eq*100:+.1f} %) / frozen "
            f"{ref['frozen']:.1f} s at eps={tc.eps:.1f} — single-gamma CF misrepresents a "
            "dissociating gas at high area ratio; set combustion.nozzle_flow"
        )
    if tc.pc_bar < _KINETIC_PC_BAR and cfg.combustion.nozzle_flow in ("single_gamma", "equilibrium") \
            and spread > _BAND_WARN:
        w.append(
            f"pc={tc.pc_bar:.1f} bar: recombination kinetics likely freeze early in the "
            f"nozzle — equilibrium Isp {ref['equilibrium']:.1f} s is an upper bound, the "
            f"frozen bound is {ref['frozen']:.1f} s ({-spread*100:.1f} %)"
        )
    return nr, tuple(w)


def _loss_warnings(est, eta_cf_source: str) -> tuple:
    w = []
    if est.re_throat < losses.RE_THROAT_WARN:
        w.append(
            f"throat Reynolds number {est.re_throat:.2e} < 1e5: boundary-layer losses of "
            f"small nozzles are significant (estimated wall-shear loss "
            f"{est.bl_loss_fraction*100:.1f} %, laminar over {est.laminar_fraction*100:.0f} % "
            "of the wetted length)"
        )
    if eta_cf_source == "input" and est.eta_cf_used > est.eta_cf_estimate + 0.01:
        w.append(
            f"eta_cf={est.eta_cf_used:.3f} is above the first-order estimate "
            f"{est.eta_cf_estimate:.3f} (divergence {est.divergence_efficiency:.3f} x "
            f"boundary layer {1-est.bl_loss_fraction:.3f}) — optimistic; consider "
            "eta_cf_source: estimate"
        )
    return tuple(w)


def run(cfg: EngineConfig) -> EngineResult:
    prop = cfg.propellants
    point = cfg.operating_point if cfg.mode == "design" else cfg.analyze_point
    coupled = cfg.coupled_temperature_side
    estimate_eta = point.eta_cf_source == "estimate"
    T_fuel, T_ox = prop.fuel_temp_K, prop.ox_temp_K
    eta_cf = point.eta_cf
    pc_hint = cfg.operating_point.pc_bar if cfg.mode == "design" else 25.0
    history: list[dict] = []
    converged = not (coupled or estimate_eta)
    regen_T_out = None
    film_res = None

    for it in range(1, _MAX_COUPLING_ITER + 1):
        # 1. combustion model (c*, Tc, gamma as functions of O/F) ----------------
        model = combustion.build_model(prop, cfg.combustion, ox_temp_K=T_ox,
                                       fuel_temp_K=T_fuel, pc_hint_bar=pc_hint)

        # 2. nominal point: design sizing OR reverse analysis --------------------
        # With film cooling, the kernel sees the combusting CORE flow (shifted
        # O/F, film subtracted); delivered totals are book-kept afterwards.
        film_warnings: tuple = ()
        op, ap = cfg.operating_point, cfg.analyze_point
        if op is not None:
            op = op.model_copy(update={"eta_cf": eta_cf})
        else:
            ap = ap.model_copy(update={"eta_cf": eta_cf})
        of_overall = None
        if cfg.film_cooling is not None:
            if cfg.mode == "design":
                op, of_overall = film.core_operating_point(op, cfg.film_cooling)
            else:
                ap, of_overall = film.core_analyze_point(ap, cfg.film_cooling)
            film_warnings = (film.MODEL_NOTE,)

        if cfg.mode == "design":
            tc = thrust_chamber.size(op, model)
            p_amb = op.p_amb_bar
        else:
            tc = thrust_chamber.analyze(cfg.geometry, ap, model)
            p_amb = ap.p_amb_bar

        comb = model.at(tc.of_ratio, pc_bar=tc.pc_bar)
        transport = model.transport(tc.of_ratio, tc.pc_bar)
        if transport:
            comb = replace(comb, **transport)

        # 3. contour generation ---------------------------------------------------
        cont = contour.generate(tc, cfg.chamber, comb.gamma)
        est = losses.estimate(cont, tc, comb)

        # 4. fixed-point updates (eta_cf estimate, regen-outlet temperature) -----
        changed = False
        if estimate_eta:
            new_eta = float(np.clip(est.eta_cf_estimate, 0.5, 1.0))
            changed |= abs(new_eta - eta_cf) > _ETA_TOL
            eta_cf = new_eta
        if coupled:
            from .regen.integration import quick_regen_outlet
            regen_T_out, _ = quick_regen_outlet(cfg, tc, comb, cont)
            old = T_fuel if coupled == "fuel" else T_ox
            changed |= abs(regen_T_out - old) > _T_TOL_K
            if coupled == "fuel":
                T_fuel = regen_T_out
            else:
                T_ox = regen_T_out
        history.append({"iteration": it, "eta_cf": round(eta_cf, 5),
                        "fuel_temp_K": round(T_fuel, 2), "ox_temp_K": round(T_ox, 2),
                        "isp_s": round(tc.isp_s, 3)})
        if not changed:
            converged = True
            break

    if estimate_eta:
        tc = replace(tc, provenance={**tc.provenance,
                                     "eta_cf": "estimated: divergence x boundary layer (first-order)"})

    if cfg.film_cooling is not None:
        mdot_total = None
        if cfg.mode == "analyze":
            mdot_total = (cfg.analyze_point.mdot_ox_kg_s
                          + cfg.analyze_point.mdot_fuel_kg_s)
        film_res = film.build_result(
            tc, cfg.film_cooling, of_overall, mdot_total_kg_s=mdot_total)

    coupling = None
    if coupled or estimate_eta:
        coupling = CouplingResult(
            iterations=len(history), converged=converged,
            fuel_temp_K=T_fuel, ox_temp_K=T_ox, regen_outlet_T_K=regen_T_out,
            coupled_side=coupled, eta_cf=eta_cf if estimate_eta else None,
            history=tuple(history),
        )
    extra_warnings: list[str] = []
    if coupling is not None and not converged:
        extra_warnings.append(
            f"pipeline coupling loop did not converge in {_MAX_COUPLING_ITER} iterations "
            f"(last: {history[-1]})")

    # 5. nozzle reference band + loss/state warnings ----------------------------
    nozzle_ref, ref_warnings = _nozzle_reference(cfg, model, tc)
    extra_warnings += list(ref_warnings)
    extra_warnings += list(_combustion_state_warnings(cfg, model))
    extra_warnings += list(_loss_warnings(est, point.eta_cf_source))

    # 6. off-design / throttle sweeps (same kernel, fixed geometry) -----------
    od = None
    if cfg.offdesign is not None:
        od = offdesign.run(cfg.offdesign, tc, model, p_amb)
        if cfg.film_cooling is not None:
            film_warnings += (
                "off-design sweeps do not model film cooling (core flow only)",
            )

    # 7. uncertainty: bounding re-runs at eta_cstar ± tol ----------------------
    unc = None
    tol = point.eta_cstar_tol
    if tol is not None:
        def _at_eta(eta):
            if cfg.mode == "design":
                return thrust_chamber.size(
                    op.model_copy(update={"eta_cstar": eta}),
                    model)
            return thrust_chamber.analyze(
                cfg.geometry,
                ap.model_copy(update={"eta_cstar": eta}),
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

    warnings = (_checks(cfg, tc, cont, pc_converged=tc.pc_converged)
                + _cooling_block_check(cfg, tc, comb, cont)
                + tuple(extra_warnings)
                + (od.notes if od else ()) + film_warnings)
    return EngineResult(
        engine=cfg.engine, config_hash=cfg.config_hash, mode=cfg.mode,
        combustion=comb, thrust_chamber=tc, contour=cont, offdesign=od,
        uncertainty=unc, film=film_res, nozzle_reference=nozzle_ref,
        losses=est, coupling=coupling, warnings=warnings,
    )


def run_file(path: str) -> EngineResult:
    return run(load_config(path))
