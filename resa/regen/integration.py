"""Bridge RESA engine results into the regen channel generator + solver."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..config.schema import ChamberConfig, EngineConfig, FilmCoolingConfig, PropellantConfig
from ..regen_channels import materials
from ..regen_channels.config import FilmCfg, RegenConfig
from ..regen_channels.contour import Contour, build_contour
from ..regen_channels.export import export_artifacts
from ..regen_channels.layout import ChannelLayout
from ..results import CombustionResult, ContourResult, ThrustChamberResult

_SPECIES_ALIASES = {
    "h2": "hydrogen", "gh2": "hydrogen", "lh2": "hydrogen", "parahydrogen": "hydrogen",
    "o2": "oxygen", "gox": "oxygen", "lox": "oxygen", "go2": "oxygen",
    "n2o": "nitrousoxide", "nitrous": "nitrousoxide",
    "ch4": "methane", "lch4": "methane", "c2h5oh": "ethanol", "etoh": "ethanol",
    "rp1": "rp1", "kerosene": "rp1", "h2o": "water",
}


def _species(name: str) -> str:
    key = re.sub(r"[\s_\-()]", "", name).lower()
    return _SPECIES_ALIASES.get(key, key)


@dataclass(frozen=True)
class RegenResult:
    """High-fidelity regen cooling analysis artifacts."""
    tag: str
    layout: ChannelLayout
    results: Optional[pd.DataFrame]
    files: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    band: Optional[dict] = None            # Bartz ± tol re-solves
    skirt: Optional[pd.DataFrame] = None   # radiation-cooled extension
    feed_budget: Optional[dict] = None
    coolant_side: Optional[str] = None

    def summary(self) -> dict:
        d = {"tag": self.tag, "n_files": len(self.files)}
        if self.results is None:
            return d
        a = self.results.attrs
        d.update({
            "Q_total_kW": round(float(a["Q_total_kW"]), 2),
            "dp_bar": round(float(self.results.dp_cell_bar.sum()), 3),
            "outlet_T_K": round(float(a["outlet_T_K"]), 2),
            "outlet_p_bar": round(float(a["outlet_p_bar"]), 2),
            "T_wall_max_K": round(float(self.results.T_wall_hot_K.max()), 1),
            "T_wall_limit_K": round(float(a.get("wall_limit_K", float("nan"))), 1),
            "wall_margin_K": round(float(a.get("wall_limit_K", float("nan"))
                                         - self.results.T_wall_hot_K.max()), 1),
            "saturation_reached": bool(a["saturation_reached"]),
            "coolant_side": self.coolant_side,
            "mdot_coolant_kg_s": round(float(a["mdot_total"]), 6),
            "coolant_mach_max": round(float(a.get("coolant_mach_max", float("nan"))), 3),
            "wall_solve_fallbacks": int(a.get("wall_solve_fallbacks", 0)),
            "n_low_re_stations": int(a.get("n_laminar_stations", 0)
                                     + a.get("n_transitional_stations", 0)),
        })
        if a.get("stress_checked"):
            d["sigma_max_MPa"] = round(float(a["sigma_max_MPa"]), 1)
            d["stress_ratio_max"] = round(float(a["stress_ratio_max"]), 3)
            d["thermal_strain_max"] = round(float(a["thermal_strain_max"]), 5)
        if self.band is not None:
            d["T_wall_max_lo_K"] = self.band["lo"]["T_wall_max_K"]
            d["T_wall_max_hi_K"] = self.band["hi"]["T_wall_max_K"]
            d["bartz_correction_tol"] = self.band["tol"]
        if self.skirt is not None:
            sa = self.skirt.attrs
            d["skirt_T_max_K"] = round(float(sa["T_wall_max_K"]), 1)
            d["skirt_T_exit_K"] = round(float(sa["T_wall_exit_K"]), 1)
            d["skirt_Q_radiated_kW"] = round(float(sa["Q_radiated_kW"]), 3)
        if self.feed_budget is not None:
            d["feed_margin_bar"] = round(float(self.feed_budget["margin_bar"]), 3)
        return d


def contour_from_resa(cont: ContourResult) -> Contour:
    i = np.argsort(cont.x_m)
    return Contour(cont.x_m[i], cont.r_m[i])


def _build_contour(cfg: RegenConfig, res_contour: ContourResult) -> Contour:
    if cfg.contour.type == "from_engine":
        if cfg.sync.contour:
            return contour_from_resa(res_contour)
        raise ValueError(
            "contour.type=from_engine but sync.contour=false — set "
            "contour.type to parametric or points"
        )
    return build_contour(cfg.contour)


def infer_coolant_side(coolant: str, coolant_side: Optional[str],
                       propellants: Optional[PropellantConfig]) -> Optional[str]:
    """Which propellant flow the coolant is. An explicit ``coolant_side`` is
    validated against the coolant species; None is inferred from the species
    (fuel or oxidizer of the engine). Returns None only when nothing can be
    inferred and nothing was given."""
    if propellants is None:
        return coolant_side
    sp = _species(coolant)
    matches = {side for side, name in (("fuel", propellants.fuel),
                                       ("oxidizer", propellants.oxidizer))
               if _species(name) == sp}
    if coolant_side is not None:
        other = "oxidizer" if coolant_side == "fuel" else "fuel"
        if matches == {other}:
            raise ValueError(
                f"regen: solver.coolant_side='{coolant_side}' but the coolant "
                f"{coolant!r} is the engine {other} "
                f"({getattr(propellants, other)}) — fix coolant_side")
        return coolant_side
    if len(matches) == 1:
        return next(iter(matches))
    if not matches:
        raise ValueError(
            f"regen: solver.coolant={coolant!r} is neither the fuel "
            f"({propellants.fuel}) nor the oxidizer ({propellants.oxidizer}); "
            "set solver.coolant_side (fuel|oxidizer) or solver.mdot_total explicitly")
    raise ValueError("regen: fuel and oxidizer are the same species; set solver.coolant_side")


def prepare_regen_config(
    regen: RegenConfig,
    tc: ThrustChamberResult,
    comb: CombustionResult,
    chamber: ChamberConfig,
    film: "FilmCoolingConfig | None" = None,
    propellants: "PropellantConfig | None" = None,
) -> RegenConfig:
    """Apply RESA nominal-point values for each sync flag that is enabled."""
    sync = regen.sync
    sol = regen.solver
    hot_updates: dict[str, float] = {}
    if sync.hot_gas_pc_bar:
        hot_updates["pc_bar"] = tc.pc_bar
    if sync.hot_gas_tc_K:
        hot_updates["tc_K"] = comb.tc_K
    if sync.hot_gas_gamma:
        hot_updates["gamma"] = comb.gamma
    if sync.hot_gas_mol_mass_kg_kmol:
        hot_updates["mol_mass_kg_kmol"] = comb.mw_kg_kmol
    if sync.hot_gas_c_star_m_s:
        # throat mass flux pc/c* of the REAL engine: effective c*
        hot_updates["c_star_m_s"] = tc.cstar_eff_m_s
    if sync.hot_gas_bartz_correction:
        hot_updates["bartz_correction"] = chamber.bartz_correction
        hot_updates["bartz_correction_tol"] = chamber.bartz_correction_tol
    if sync.hot_gas_transport and comb.has_transport:
        eq = sol.hot_gas.property_basis == "equilibrium"
        cp = comb.cp_eq_J_kgK if eq else comb.cp_frozen_J_kgK
        pr = comb.pr_eq if eq else comb.pr_frozen
        if cp is not None and pr is not None:
            hot_updates.update(cp_J_kgK=cp, pr=pr, mu_pa_s=comb.mu_Pa_s)
        elif comb.cp_frozen_J_kgK is not None:
            hot_updates.update(cp_J_kgK=comb.cp_frozen_J_kgK, pr=comb.pr_frozen,
                               mu_pa_s=comb.mu_Pa_s)
    if sync.hot_gas_throat_curvature:
        hot_updates["throat_curvature_factor"] = 0.5 * (
            chamber.rt_upstream_factor + chamber.rt_downstream_factor)

    hot = sol.hot_gas.model_copy(update=hot_updates)
    side = infer_coolant_side(sol.coolant, sol.coolant_side, propellants)
    solver_updates: dict = {"hot_gas": hot, "mdot_from_engine": sync.mdot,
                            "coolant_side": side}
    if sync.of_ratio:
        solver_updates["of_ratio"] = tc.of_ratio
    if sync.mdot:
        if sol.coolant_fraction is not None:
            mdot = tc.mdot_total_kg_s * sol.coolant_fraction
        elif side == "fuel":
            mdot = tc.mdot_fuel_kg_s
        elif side == "oxidizer":
            mdot = tc.mdot_ox_kg_s
        else:
            raise ValueError(
                "regen: sync.mdot needs a coolant side — set solver.coolant_side "
                "or solver.coolant_fraction")
        solver_updates["mdot_total"] = mdot
    mdot_final = solver_updates.get("mdot_total", sol.mdot_total)
    if side is not None and mdot_final is not None:
        avail = tc.mdot_fuel_kg_s if side == "fuel" else tc.mdot_ox_kg_s
        if mdot_final > avail * (1.0 + 1e-9):
            raise ValueError(
                f"regen: coolant flow {mdot_final*1e3:.3f} g/s exceeds the engine "
                f"{side} flow {avail*1e3:.3f} g/s — the {side} cannot cool the chamber "
                "with more than its own flow (check coolant_fraction / mdot_total)")
    if film is not None:
        solver_updates["film"] = FilmCfg(
            injection_x_m=film.injection_x_m,
            effectiveness_length_m=film.effectiveness_length_m,
            film_temp_K=film.film_temp_K,
        )
    solver = sol.model_copy(update=solver_updates)
    return regen.model_copy(update={"solver": solver})


def solve_regen(regen: RegenConfig, res_contour: ContourResult):
    """Layout + solve a PREPARED regen config; no artifacts. -> (layout, df, solver)."""
    from ..regen_channels.solver import RegenSolver
    contour = _build_contour(regen, res_contour)
    lay = ChannelLayout(contour, regen)
    sol = RegenSolver(lay, regen)
    return lay, sol.solve(), sol


def _solve_skirt(regen: RegenConfig, lay: ChannelLayout, sol, contour: Contour):
    sk = regen.solver.skirt
    if not sk.enabled or lay.x[-1] >= contour.x_max - 1e-9:
        return None
    from ..regen_channels.skirt import solve_radiation_skirt
    n = max(20, int(round((contour.x_max - lay.x[-1]) / max(np.mean(np.diff(lay.x)), 1e-6))))
    xs = np.linspace(lay.x[-1], contour.x_max, min(n, 400))
    df = solve_radiation_skirt(sol.hot, xs, contour.r(xs), lay.x_throat,
                               sk.emissivity, sk.T_env_K)
    mat = materials.resolve(sk.material)
    limit = sk.max_wall_temp_K if sk.max_wall_temp_K is not None else (
        mat.max_service_T_K if mat else None)
    df.attrs["limit_K"] = limit
    df.attrs["material"] = mat.name if mat else (sk.material or "")
    return df


def run_regen(
    regen: RegenConfig,
    res_contour: ContourResult,
    out_dir: str | Path,
) -> RegenResult:
    """Run layout + optional solver and write the standard regen export set.
    ``regen`` must already be prepared (see prepare_regen_config) when it is
    attached to an engine."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = regen.meta.name.replace(" ", "_")
    warnings: list[str] = []

    contour = _build_contour(regen, res_contour)
    lay = ChannelLayout(contour, regen)

    ch = regen.channels
    if regen.contour.type == "from_engine" and ch.start_x is not None and ch.start_x > -1e-6:
        warnings.append(
            f"regen: channels.start_x={ch.start_x * 1e3:.2f} mm is at or downstream "
            "of the throat (x=0). RESA engine contours put the chamber at x<0 — "
            "omit start_x for full axial coverage"
        )

    results = None
    band = skirt = feed = None
    side = regen.solver.coolant_side
    if regen.solver.enabled:
        from ..regen_channels.solver import RegenSolver
        sol = RegenSolver(lay, regen)
        results = sol.solve()
        a = results.attrs
        t_max = float(results.T_wall_hot_K.max())
        if a["saturation_reached"]:
            warnings.append(
                "regen: bulk coolant reached saturation — two-phase bulk flow "
                "in part of the circuit"
            )
        if t_max > a["wall_limit_K"]:
            warnings.append(
                f"regen: hot wall {t_max:.0f} K exceeds the {a['wall_limit_K']:.0f} K "
                f"limit ({a['wall_limit_source']})"
            )
        if a.get("wall_solve_fallbacks", 0):
            warnings.append(
                f"regen: wall energy balance did not bracket at "
                f"{a['wall_solve_fallbacks']} station(s) — those wall temperatures "
                "are bracket ends, not solutions"
            )
        n_low = a.get("n_laminar_stations", 0) + a.get("n_transitional_stations", 0)
        if n_low:
            low = results[results.Re < 4000.0]
            warnings.append(
                f"regen: coolant Re < 4000 at {n_low} of {len(results)} stations "
                f"(x {low.x_m.min()*1e3:.1f}..{low.x_m.max()*1e3:.1f} mm, "
                f"min Re {results.Re.min():.0f}) — laminar/transitional HTC is uncertain"
            )
        if np.isfinite(a.get("coolant_mach_max", np.nan)) and \
                a["coolant_mach_max"] > regen.solver.max_coolant_mach:
            warnings.append(
                f"regen: coolant Mach {a['coolant_mach_max']:.2f} exceeds "
                f"{regen.solver.max_coolant_mach:.2f} — compressibility / choking risk"
            )
        if a.get("hot_gas_fallback_properties"):
            warnings.append(
                f"regen: Bartz uses fallback transport properties ({a['hot_gas_property_note']}) "
                "— sync CEA transport (rocketcea) or set solver.hot_gas.mu_pa_s/pr/cp_J_kgK"
            )
        if a.get("stress_checked") and a["stress_ratio_max"] > a["stress_ratio_warn"]:
            i = int(results.stress_ratio.idxmax())
            warnings.append(
                f"regen: hot-wall thermal+pressure stress {a['sigma_max_MPa']:.0f} MPa vs "
                f"yield {results.yield_MPa[i]:.0f} MPa at x={results.x_m[i]*1e3:.1f} mm "
                f"(ratio {a['stress_ratio_max']:.2f}, thermal strain "
                f"{a['thermal_strain_max']*100:.2f} %) — wall is in the plastic regime; "
                "low-cycle fatigue governs life (first-order Huzel & Huang)"
            )

        # Bartz ± tol band
        tol = regen.solver.hot_gas.bartz_correction_tol
        if tol:
            band = {"tol": tol}
            for key, sgn in (("lo", -1.0), ("hi", +1.0)):
                hg = regen.solver.hot_gas.model_copy(update={
                    "bartz_correction": max(regen.solver.hot_gas.bartz_correction + sgn * tol, 1e-3),
                    "bartz_correction_tol": None})
                rb = regen.model_copy(update={"solver": regen.solver.model_copy(update={"hot_gas": hg})})
                dfb = RegenSolver(lay, rb).solve()
                band[key] = {
                    "bartz_correction": hg.bartz_correction,
                    "T_wall_max_K": round(float(dfb.T_wall_hot_K.max()), 1),
                    "Q_total_kW": round(float(dfb.attrs["Q_total_kW"]), 3),
                    "outlet_T_K": round(float(dfb.attrs["outlet_T_K"]), 1),
                }
            if band["hi"]["T_wall_max_K"] > a["wall_limit_K"] >= t_max:
                warnings.append(
                    f"regen: hot wall within limit at Bartz {regen.solver.hot_gas.bartz_correction:g} "
                    f"but {band['hi']['T_wall_max_K']:.0f} K at +{tol:g} — margin depends on "
                    "the uncalibrated Bartz factor"
                )

        # radiation-cooled skirt
        skirt = _solve_skirt(regen, lay, sol, contour)
        if skirt is not None:
            sa = skirt.attrs
            if sa.get("limit_K") is not None and sa["T_wall_max_K"] > sa["limit_K"]:
                warnings.append(
                    f"regen: radiation-cooled skirt reaches {sa['T_wall_max_K']:.0f} K "
                    f"at x={skirt.x_m[skirt.T_wall_K.idxmax()]*1e3:.1f} mm, above the "
                    f"{sa['limit_K']:.0f} K limit ({sa.get('material') or 'config'})"
                )

        # feed-pressure budget (coolant feeds the injector)
        if side is not None:
            pc_bar = regen.solver.hot_gas.pc_bar
            required = pc_bar * (1.0 + regen.solver.injector_dp_fraction)
            margin = a["outlet_p_bar"] - required
            feed = {"outlet_p_bar": round(float(a["outlet_p_bar"]), 3),
                    "required_p_bar": round(required, 3),
                    "injector_dp_fraction": regen.solver.injector_dp_fraction,
                    "margin_bar": round(float(margin), 3)}
            if margin < 0:
                warnings.append(
                    f"regen: coolant outlet {a['outlet_p_bar']:.2f} bar is below "
                    f"pc x (1 + {regen.solver.injector_dp_fraction:g}) = {required:.2f} bar "
                    f"— raise inlet pressure by {-margin:.2f} bar or cut channel losses"
                )

    files: list[str] = []
    export_files, export_warnings = export_artifacts(
        lay, regen, results, out_dir=out_dir, tag=tag,
    )
    files.extend(export_files)
    warnings.extend(export_warnings)
    if skirt is not None:
        f = out_dir / f"{tag}_skirt.csv"
        skirt.to_csv(f, index=False)
        files.append(str(f))

    return RegenResult(
        tag=tag, layout=lay, results=results,
        files=tuple(files), warnings=tuple(warnings),
        band=band, skirt=skirt, feed_budget=feed, coolant_side=side,
    )


def run_regen_for_engine(
    cfg: EngineConfig,
    tc: ThrustChamberResult,
    comb: CombustionResult,
    res_contour: ContourResult,
    out_dir: str | Path,
) -> RegenResult:
    if cfg.regen is None:
        raise ValueError("engine config has no regen block")
    regen = prepare_regen_config(
        cfg.regen, tc, comb, cfg.chamber, film=cfg.film_cooling,
        propellants=cfg.propellants)
    return run_regen(regen, res_contour, out_dir)


def quick_regen_outlet(
    cfg: EngineConfig,
    tc: ThrustChamberResult,
    comb: CombustionResult,
    res_contour: ContourResult,
) -> tuple[float, str]:
    """Coolant outlet temperature [K] and side for the pipeline's
    regen-outlet -> propellant temperature coupling (no artifacts)."""
    regen = prepare_regen_config(
        cfg.regen, tc, comb, cfg.chamber, film=cfg.film_cooling,
        propellants=cfg.propellants)
    _, df, _ = solve_regen(regen, res_contour)
    return float(df.attrs["outlet_T_K"]), regen.solver.coolant_side
