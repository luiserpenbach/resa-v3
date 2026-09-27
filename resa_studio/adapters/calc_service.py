"""Stateless calculations for the Studio: every call takes a complete engine
design dict and returns plain JSON. No disk writes, so the same service runs
locally and on serverless hosts.

    performance   sizing + geometry (off-design sweeps stripped for speed)
    heat_flux     Bartz hand-calc at an assumed wall temperature
    cooling       full regen channel solve: margins, coolant path, p-h data
    geometry      channel layout profiles, throat section, 3D assembly
    offdesign     throttle / mixture-ratio sweeps
    trade_study   one input swept over a range -> key results
    catalog       propellants, materials, backends for the UI pickers
"""
from __future__ import annotations

import copy
import math
import tempfile
import time
from typing import Any, Optional

import numpy as np
from pydantic import ValidationError

from resa.config.schema import EngineConfig
from resa.models import heatflux
from resa.results import offdesign_to_dict

from resa_studio.adapters import preview_service
from resa_studio.adapters.preview_cache import PIPELINE_CACHE


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _num(v: Any) -> Any:
    """JSON-safe number (NaN/inf -> None, numpy -> python)."""
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return f if math.isfinite(f) else None


def _arr(a: Any) -> list:
    return [_num(v) for v in np.asarray(a, dtype=float).ravel()]


def validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Pydantic errors -> [{path, message}] with paths into the design dict."""
    out = []
    for e in exc.errors():
        msg = str(e.get("msg", "invalid"))
        msg = msg.removeprefix("Value error, ").removeprefix("Assertion failed, ")
        out.append({"path": [p for p in e.get("loc", ()) if isinstance(p, (str, int))],
                    "message": msg})
    return out


def validate(design: dict[str, Any]) -> dict[str, Any]:
    try:
        cfg = EngineConfig.model_validate(design)
    except ValidationError as exc:
        return {"ok": False, "errors": validation_errors(exc)}
    return {"ok": True, "errors": [], "mode": cfg.mode}


def _strip_offdesign(design: dict[str, Any]) -> dict[str, Any]:
    d = dict(design)
    d.pop("config_hash", None)
    d["offdesign"] = None
    return d


def _pipeline(design: dict[str, Any], *, keep_offdesign: bool = False):
    data = dict(design) if keep_offdesign else _strip_offdesign(design)
    data.pop("config_hash", None)
    return PIPELINE_CACHE.get_or_run(data, EngineConfig.model_validate)


_AREAS = (
    ("cooling", ("regen", "coolant", "wall", "channel", "skirt", "saturat", "film", "bartz")),
    ("nozzle", ("nozzle", "separation", "eta_cf", "exit", "boundary-layer", "reynolds",
                "kinetics", "frozen", "single_gamma")),
    ("chamber", ("l*", "chamber length", "contraction", "contour")),
    ("propellants", ("propellant", "delivery", "cea default", "rocketcea", "nasa cea")),
)


def friendly_warnings(warnings) -> list[dict[str, str]]:
    out = []
    for w in warnings:
        low = str(w).lower()
        area = next((a for a, keys in _AREAS if any(k in low for k in keys)), "performance")
        out.append({"area": area, "message": str(w)})
    return out


# --------------------------------------------------------------------------- #
# performance
# --------------------------------------------------------------------------- #
def _performance_payload(cfg: EngineConfig, res) -> dict[str, Any]:
    tc, comb, cont = res.thrust_chamber, res.combustion, res.contour
    perf = {
        "thrust_N": tc.thrust_N, "isp_s": tc.isp_s, "pc_bar": tc.pc_bar,
        "of_ratio": tc.of_ratio, "eps": tc.eps, "pe_bar": tc.pe_bar, "cf": tc.cf,
        "exit_mach": tc.exit_mach, "mdot_total_kg_s": tc.mdot_total_kg_s,
        "mdot_ox_kg_s": tc.mdot_ox_kg_s, "mdot_fuel_kg_s": tc.mdot_fuel_kg_s,
        "cstar_m_s": tc.cstar_eff_m_s, "cstar_ideal_m_s": comb.cstar_ideal_m_s,
        "eta_cstar": tc.eta_cstar, "eta_cf": tc.eta_cf, "tc_K": comb.tc_K,
        "gamma": comb.gamma, "mw_kg_kmol": comb.mw_kg_kmol,
        "separated": tc.separated, "isp_vac_ideal_s": tc.isp_vac_ideal_s,
        "p_amb_bar": (cfg.operating_point or cfg.analyze_point).p_amb_bar,
    }
    # vacuum Isp of the real engine: ideal vacuum CF scaled by eta_cf, at the
    # effective c*
    if tc.isp_vac_ideal_s is not None:
        perf["isp_vac_s"] = tc.isp_vac_ideal_s * tc.eta_cstar * tc.eta_cf
    if res.uncertainty is not None:
        u = res.uncertainty
        perf["band"] = {"eta_tol": u.eta_tol, "isp_lo_s": u.tc_lo.isp_s, "isp_hi_s": u.tc_hi.isp_s,
                        "pc_lo_bar": u.tc_lo.pc_bar, "pc_hi_bar": u.tc_hi.pc_bar}
    if res.nozzle_reference is not None:
        r = res.nozzle_reference
        perf["nozzle_models"] = {
            "selected": r.selected, "single_gamma": r.isp_vac_single_gamma_s,
            "equilibrium": r.isp_vac_equilibrium_s, "frozen": r.isp_vac_frozen_s,
            "frozen_at_throat": r.isp_vac_frozen_at_throat_s}
    if res.losses is not None:
        lo = res.losses
        perf["losses"] = {"re_throat": lo.re_throat, "eta_cf_estimate": lo.eta_cf_estimate,
                          "divergence_efficiency": lo.divergence_efficiency,
                          "bl_loss_fraction": lo.bl_loss_fraction}
    if res.coupling is not None:
        c = res.coupling
        perf["coupling"] = {"iterations": c.iterations, "converged": c.converged,
                            "fuel_temp_K": c.fuel_temp_K, "ox_temp_K": c.ox_temp_K,
                            "regen_outlet_T_K": c.regen_outlet_T_K, "side": c.coupled_side}
    if res.film is not None:
        perf["film"] = res.film.summary()

    i = np.argsort(cont.x_m)
    x, r = cont.x_m[i], cont.r_m[i]
    vol = float(np.trapezoid(np.pi * r[x <= 0] ** 2, x[x <= 0]))
    geometry = {
        "throat_diameter_m": 2 * tc.throat_radius_m, "exit_diameter_m": 2 * tc.exit_radius_m,
        "chamber_diameter_m": 2 * cont.chamber_radius_m,
        "chamber_length_m": cont.chamber_length_m, "convergent_length_m": cont.convergent_length_m,
        "cylinder_length_m": max(cont.chamber_length_m - cont.convergent_length_m, 0.0),
        "nozzle_length_m": cont.divergent_length_m, "total_length_m": cont.total_length_m,
        "contraction_ratio": cont.contraction_ratio, "eps": cont.eps,
        "theta_n_deg": cont.theta_n_deg, "theta_e_deg": cont.theta_e_deg,
        "chamber_volume_m3": vol, "l_star_m": vol / tc.throat_area_m2,
        "contour_method": cont.method,
    }
    return {
        "engine": cfg.engine, "mode": cfg.mode,
        "performance": {k: _num(v) if not isinstance(v, dict) else
                        {kk: _num(vv) for kk, vv in v.items()} for k, v in perf.items()},
        "geometry": {k: _num(v) for k, v in geometry.items()},
        "contour": {"x_m": _arr(x), "r_m": _arr(r)},
        "propellant_states": {"oxidizer": comb.ox_state, "fuel": comb.fuel_state,
                              "chemistry": comb.source, "nozzle_flow": comb.nozzle_flow},
        "provenance": dict(tc.provenance),
        "warnings": friendly_warnings(res.warnings),
    }


def performance(design: dict[str, Any]) -> dict[str, Any]:
    t = time.perf_counter()
    cfg, res = _pipeline(design)
    out = _performance_payload(cfg, res)
    out["ok"] = True
    out["elapsed_s"] = round(time.perf_counter() - t, 3)
    return out


# --------------------------------------------------------------------------- #
# heat flux hand-calc
# --------------------------------------------------------------------------- #
def heat_flux(design: dict[str, Any], wall_temp_K: float = 800.0,
              coolant_pressure_bar: Optional[float] = None) -> dict[str, Any]:
    cfg, res = _pipeline(design)
    e = heatflux.estimate(cfg, res, wall_temp_K, coolant_pressure_bar)
    return {
        "ok": True,
        "wall_temp_K": e.wall_temp_K,
        "profiles": {
            "x_m": _arr(e.x_m), "r_m": _arr(e.r_m), "mach": _arr(e.mach),
            "t_aw_K": _arr(e.t_aw_K), "h_g_W_m2K": _arr(e.h_g_W_m2K), "q_W_m2": _arr(e.q_W_m2),
            "q_lo_W_m2": _arr(e.q_lo_W_m2) if e.q_lo_W_m2 is not None else None,
            "q_hi_W_m2": _arr(e.q_hi_W_m2) if e.q_hi_W_m2 is not None else None,
        },
        "summary": {
            "q_max_W_m2": _num(e.q_max_W_m2), "x_q_max_m": _num(e.x_q_max_m),
            "q_throat_W_m2": _num(e.q_throat_W_m2), "Q_total_W": _num(e.Q_total_W),
            "Q_chamber_W": _num(e.Q_chamber_W), "Q_nozzle_W": _num(e.Q_nozzle_W),
            "wetted_area_m2": _num(e.wetted_area_m2),
            "t_aw_throat_K": _num(e.t_aw_K[int(np.argmin(e.r_m))]),
            "bartz_correction": cfg.chamber.bartz_correction,
            "bartz_correction_tol": cfg.chamber.bartz_correction_tol,
        },
        "coolant_capacity": [{k: _num(v) for k, v in c.__dict__.items()} for c in e.coolant],
        "property_note": e.property_note,
    }


# --------------------------------------------------------------------------- #
# cooling channels (regen)
# --------------------------------------------------------------------------- #
def _ph_diagram(coolant_name: str, p_lo_bar: float, p_hi_bar: float,
                t_lo: float, t_hi: float) -> dict[str, Any]:
    """Saturation dome + a few isotherms on p-h axes for the coolant."""
    from CoolProp.CoolProp import PropsSI

    from resa.regen_channels.coolant import Coolant
    fl = Coolant(coolant_name).cp_name
    p_crit, T_crit = PropsSI("PCRIT", fl), PropsSI("TCRIT", fl)
    try:
        p_trip = PropsSI("PTRIPLE", fl)
    except ValueError:
        p_trip = 1e3
    out: dict[str, Any] = {"fluid": fl, "p_crit_bar": p_crit / 1e5, "T_crit_K": T_crit}
    try:
        out["h_crit_kJ_kg"] = PropsSI("H", "T", T_crit, "P", p_crit, fl) / 1e3
    except ValueError:
        out["h_crit_kJ_kg"] = None

    p_min = max(p_trip * 1.01, min(p_lo_bar * 1e5 * 0.2, p_crit * 0.05), 1e3)
    ps = np.geomspace(p_min, p_crit * 0.999, 70)
    dome_l, dome_v = [], []
    for p in ps:
        try:
            dome_l.append((PropsSI("H", "P", p, "Q", 0, fl) / 1e3, p / 1e5))
            dome_v.append((PropsSI("H", "P", p, "Q", 1, fl) / 1e3, p / 1e5))
        except ValueError:
            continue
    out["dome"] = {"h_liquid_kJ_kg": [h for h, _ in dome_l], "p_liquid_bar": [p for _, p in dome_l],
                   "h_vapor_kJ_kg": [h for h, _ in dome_v], "p_vapor_bar": [p for _, p in dome_v]}

    # isotherms spanning the coolant path
    lo, hi = max(t_lo * 0.9, PropsSI("TMIN", fl) + 0.5), t_hi * 1.1
    temps = np.unique(np.round(np.linspace(lo, hi, 6), -1 if hi - lo > 60 else 0))
    p_axis = np.geomspace(max(p_min, p_lo_bar * 1e5 * 0.3), max(p_hi_bar * 1e5 * 3.0, p_crit * 1.5), 60)
    isotherms = []
    for T in temps:
        hs, pp = [], []
        p_sat = None
        if T < T_crit:
            try:
                p_sat = PropsSI("P", "T", T, "Q", 0, fl)
            except ValueError:
                p_sat = None
        for p in p_axis:
            if p_sat is not None and pp and pp[-1] * 1e5 < p_sat <= p:
                # horizontal two-phase segment at p_sat
                try:
                    hs += [PropsSI("H", "T", T, "Q", 1, fl) / 1e3, PropsSI("H", "T", T, "Q", 0, fl) / 1e3]
                    pp += [p_sat / 1e5, p_sat / 1e5]
                except ValueError:
                    pass
            try:
                hs.append(PropsSI("H", "T", T, "P", p, fl) / 1e3)
                pp.append(p / 1e5)
            except ValueError:
                continue
        if len(hs) > 2:
            isotherms.append({"T_K": float(T), "h_kJ_kg": hs, "p_bar": pp})
    out["isotherms"] = isotherms
    return out


def cooling(design: dict[str, Any], fidelity: str = "preview") -> dict[str, Any]:
    """Regen solve with bands, skirt and feed budget; no artifacts."""
    from resa.regen.integration import prepare_regen_config, run_regen

    t0 = time.perf_counter()
    cfg, res = _pipeline(design)
    if cfg.regen is None:
        return {"ok": False, "error": "This design has no cooling channels yet."}
    regen = prepare_regen_config(cfg.regen, res.thrust_chamber, res.combustion, cfg.chamber,
                                 film=cfg.film_cooling, propellants=cfg.propellants)
    if not regen.solver.enabled:
        return {"ok": False, "error": "The channel solver is switched off for this design."}
    n_full = regen.geometry.n_stations
    n = n_full if fidelity == "full" else min(90, max(45, n_full // 3))
    no_files = {k: False for k in ("stl", "step", "centerlines_csv", "geometry_csv",
                                   "results_csv", "html_3d", "html_plots")}
    regen = regen.model_copy(update={
        "geometry": regen.geometry.model_copy(update={"n_stations": n}),
        "export": regen.export.model_copy(update=no_files),
    })
    with tempfile.TemporaryDirectory() as tmp:
        try:
            rr = run_regen(regen, res.contour, tmp)
        except Exception as exc:  # solver errors are design feedback, not crashes
            return {"ok": False, "error": str(exc)}
    df, lay, a = rr.results, rr.layout, rr.results.attrs
    summary = {k: _num(v) for k, v in rr.summary().items() if not isinstance(v, str)}
    i_hot = int(df.T_wall_hot_K.idxmax())
    summary.update(
        coolant=cfg.regen.solver.coolant, coolant_side=rr.coolant_side,
        x_T_wall_max_m=_num(df.x_m.iloc[i_hot]),
        q_max_W_m2=_num(df.q_w_W_m2.max()),
        inlet_T_K=_num(a["inlet_T_K"]), inlet_p_bar=_num(regen.solver.inlet.pressure_bar),
        inlet_location=a["coolant_inlet_location"], correlation=a["coolant_correlation"],
        wall_material=a["wall_material"], wall_limit_source=a["wall_limit_source"],
        n_channels=int(lay.N), stations=n, full_stations=n_full,
        energy_balance_kW=_num(a["energy_balance_kW"]),
        hot_gas_note=a.get("hot_gas_property_note", ""),
    )
    if rr.feed_budget is not None:
        summary["feed_required_p_bar"] = _num(rr.feed_budget["required_p_bar"])
    # layout at the solver stations
    j = np.searchsorted(lay.x, df.x_m.to_numpy()).clip(0, len(lay.x) - 1)
    profiles = {c: _arr(df[c]) for c in (
        "x_m", "r_m", "T_wall_hot_K", "T_wall_cold_K", "T_aw_K", "T_cool_K", "T_cool_out_K",
        "T_sat_K", "p_cool_bar", "p_cool_out_bar", "h_J_kg", "h_out_J_kg", "q_w_W_m2", "h_g",
        "h_c", "v_m_s", "Re", "mach_cool", "quality", "rho", "stress_ratio",
        "sigma_total_MPa", "yield_MPa", "p_gas_bar")}
    profiles.update(channel_width_m=_arr(lay.w[j]), channel_height_m=_arr(lay.h[j]),
                    rib_width_m=_arr(lay.t_rib[j]), wall_thickness_m=_arr(lay.t_wall[j]))
    # coolant path in flow order (inlet -> outlet) for the p-h / T-x plots
    order = df.sort_values("x_m", ascending=(a["coolant_inlet_location"] != "nozzle_end"))
    path = {
        "x_m": _arr(order.x_m),
        "h_kJ_kg": _arr(np.r_[order.h_J_kg.iloc[0], order.h_out_J_kg] / 1e3),
        "p_bar": _arr(np.r_[order.p_cool_bar.iloc[0], order.p_cool_out_bar]),
        "T_K": _arr(np.r_[order.T_cool_K.iloc[0], order.T_cool_out_K]),
    }
    T_path = np.asarray(path["T_K"], dtype=float)
    try:
        ph = _ph_diagram(regen.solver.coolant, float(np.nanmin(path["p_bar"])),
                         float(np.nanmax(path["p_bar"])), float(np.nanmin(T_path)),
                         float(np.nanmax(T_path)))
    except Exception as exc:
        ph = {"error": str(exc)}
    out: dict[str, Any] = {
        "ok": True, "fidelity": "full" if n == n_full else "preview",
        "summary": summary, "profiles": profiles, "path": path, "ph": ph,
        "wall_limit_K": _num(a["wall_limit_K"]),
        "warnings": friendly_warnings(rr.warnings),
    }
    if rr.band is not None:
        out["band"] = rr.band
    if rr.skirt is not None:
        sk = rr.skirt
        out["skirt"] = {"x_m": _arr(sk.x_m), "T_wall_K": _arr(sk.T_wall_K),
                        "limit_K": _num(sk.attrs.get("limit_K")),
                        "material": sk.attrs.get("material", "")}
    out["elapsed_s"] = round(time.perf_counter() - t0, 3)
    return out


def geometry(design: dict[str, Any], x_m: Optional[float] = None) -> dict[str, Any]:
    """Channel layout profiles + one cross-section + 3D assembly payload."""
    data = _strip_offdesign(design)
    section = preview_service.preview_cooling_section(data, x_m)
    assembly = preview_service.preview_cooling_assembly3d(data)
    return {"ok": True, "section": section, "assembly": assembly}


def export_channel(design: dict[str, Any], channel_id: int = 0, fmt: str = "stl"):
    return preview_service.export_channel(_strip_offdesign(design), channel_id, fmt)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# operating range
# --------------------------------------------------------------------------- #
def offdesign(design: dict[str, Any]) -> dict[str, Any]:
    if not design.get("offdesign"):
        return {"ok": False, "error": "No operating-range sweeps are set up for this design."}
    t = time.perf_counter()
    cfg, res = _pipeline(design, keep_offdesign=True)
    return {"ok": True, "offdesign": offdesign_to_dict(res.offdesign),
            "nominal": {"thrust_N": res.thrust_chamber.thrust_N, "of_ratio": res.thrust_chamber.of_ratio,
                        "isp_s": res.thrust_chamber.isp_s, "pc_bar": res.thrust_chamber.pc_bar},
            "elapsed_s": round(time.perf_counter() - t, 3)}


# --------------------------------------------------------------------------- #
# trade study
# --------------------------------------------------------------------------- #
TRADE_PARAMETERS: dict[str, dict[str, Any]] = {
    "operating_point.pc_bar": {"label": "Chamber pressure", "unit": "bar"},
    "operating_point.thrust_N": {"label": "Thrust", "unit": "N"},
    "operating_point.of_ratio": {"label": "Mixture ratio (O/F)", "unit": ""},
    "operating_point.eps": {"label": "Nozzle area ratio", "unit": ""},
    "operating_point.eta_cstar": {"label": "Combustion efficiency", "unit": ""},
    "chamber.contraction_ratio": {"label": "Contraction ratio", "unit": ""},
    "chamber.l_star_m": {"label": "Characteristic length L*", "unit": "m"},
    "regen.solver.inlet.pressure_bar": {"label": "Coolant inlet pressure", "unit": "bar"},
    "regen.solver.inlet.temperature_K": {"label": "Coolant inlet temperature", "unit": "K"},
    "regen.channels.count": {"label": "Number of channels", "unit": ""},
}


def _set_path(d: dict, path: str, value: Any) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        if d.get(k) is None:
            raise ValueError(f"design has no {'.'.join(keys[:-1])} section")
        d = d[k]
    d[keys[-1]] = value


def trade_study(design: dict[str, Any], parameter: str, values: list[float],
                include: tuple[str, ...] = ("heat_flux",), wall_temp_K: float = 800.0
                ) -> dict[str, Any]:
    if parameter not in TRADE_PARAMETERS:
        raise ValueError(f"unsupported trade-study parameter {parameter!r}")
    if not 2 <= len(values) <= 25:
        raise ValueError("give 2 to 25 values")
    t = time.perf_counter()
    rows = []
    for v in values:
        d = _strip_offdesign(copy.deepcopy(design))
        val: Any = int(round(v)) if parameter.endswith(".count") else float(v)
        _set_path(d, parameter, val)
        if parameter == "operating_point.eps":
            d["operating_point"]["pe_bar"] = None
        row: dict[str, Any] = {"value": val}
        try:
            cfg, res = _pipeline(d)
            tc = res.thrust_chamber
            row.update(ok=True, isp_s=tc.isp_s, thrust_N=tc.thrust_N, pc_bar=tc.pc_bar,
                       of_ratio=tc.of_ratio, eps=tc.eps, mdot_kg_s=tc.mdot_total_kg_s,
                       throat_diameter_m=2 * tc.throat_radius_m,
                       exit_diameter_m=2 * tc.exit_radius_m, tc_K=res.combustion.tc_K,
                       total_length_m=res.contour.total_length_m, n_warnings=len(res.warnings))
            if "heat_flux" in include:
                e = heatflux.estimate(cfg, res, wall_temp_K)
                row.update(q_max_W_m2=e.q_max_W_m2, Q_total_W=e.Q_total_W)
            if "cooling" in include and cfg.regen is not None:
                c = cooling(d, "preview")
                if c.get("ok"):
                    s = c["summary"]
                    row.update(T_wall_max_K=s.get("T_wall_max_K"), wall_margin_K=s.get("wall_margin_K"),
                               dp_bar=s.get("dp_bar"), outlet_T_K=s.get("outlet_T_K"))
                else:
                    row["cooling_error"] = str(c.get("error", "cooling solve failed"))
        except (ValidationError, ValueError, RuntimeError) as exc:
            msg = validation_errors(exc)[0]["message"] if isinstance(exc, ValidationError) else str(exc)
            row.update(ok=False, error=msg)
        rows.append({k: _num(v) if not isinstance(v, str) else v for k, v in row.items()})
    return {"ok": True, "parameter": parameter, **TRADE_PARAMETERS[parameter], "rows": rows,
            "elapsed_s": round(time.perf_counter() - t, 3)}


# --------------------------------------------------------------------------- #
# catalog
# --------------------------------------------------------------------------- #
PROPELLANT_CHOICES = [
    # id, label, role, CoolProp fluid (None: no fluid model), CEA name, phase, T [K]
    ("lox", "Liquid oxygen (LOX)", "oxidizer", "Oxygen", "LOX", "liquid", 90.0),
    ("gox", "Gaseous oxygen (GOX)", "oxidizer", "Oxygen", "GOX", "gas", 290.0),
    ("n2o", "Nitrous oxide (N2O)", "oxidizer", "NitrousOxide", "N2O", "liquid", 280.0),
    ("n2o4", "Nitrogen tetroxide (NTO)", "oxidizer", None, "N2O4", "liquid", 298.15),
    ("h2o2", "Hydrogen peroxide (100 %)", "oxidizer", None, "H2O2", "liquid", 298.15),
    ("lh2", "Liquid hydrogen (LH2)", "fuel", "Hydrogen", "LH2", "liquid", 20.3),
    ("gh2", "Gaseous hydrogen (GH2)", "fuel", "Hydrogen", "GH2", "gas", 290.0),
    ("lch4", "Liquid methane (LCH4)", "fuel", "Methane", "CH4", "liquid", 112.0),
    ("ethanol", "Ethanol", "fuel", "Ethanol", "Ethanol", "liquid", 293.15),
    ("methanol", "Methanol", "fuel", "Methanol", "Methanol", "liquid", 293.15),
    ("propane", "Propane", "fuel", "n-Propane", "Propane", "liquid", 231.0),
    ("rp1", "RP-1 (kerosene)", "fuel", "n-Dodecane", "RP1", "liquid", 293.15),
    ("mmh", "MMH", "fuel", None, "MMH", "liquid", 298.15),
    ("ammonia", "Ammonia", "fuel", "Ammonia", "NH3", "liquid", 240.0),
]


def catalog() -> dict[str, Any]:
    from resa.properties import nasa_cea
    from resa.regen_channels.materials import MATERIALS
    try:
        import rocketcea  # noqa: F401
        has_rocketcea = True
    except ImportError:
        has_rocketcea = False
    return {
        "propellants": [
            {"id": i, "label": lab, "role": role, "fluid": fl, "cea_name": cn,
             "phase": ph, "temperature_K": T, "can_cool": fl is not None}
            for i, lab, role, fl, cn, ph, T in PROPELLANT_CHOICES],
        "materials": [
            {"key": m.key, "name": m.name, "max_service_T_K": m.max_service_T_K,
             "k_300K_W_mK": m.k(300.0), "yield_300K_MPa": m.yield_MPa(300.0), "note": m.note}
            for m in MATERIALS.values()],
        "chemistry": {"cea": nasa_cea.available(), "rocketcea": has_rocketcea},
        "trade_parameters": [{"path": k, **v} for k, v in TRADE_PARAMETERS.items()],
    }


# --------------------------------------------------------------------------- #
# YAML in / out (CLI-compatible engine files)
# --------------------------------------------------------------------------- #
def parse_yaml(text: str) -> dict[str, Any]:
    """Engine YAML text -> design dict. Self-contained files only: `base:` and
    fragment references need the files next to them (use the CLI loader)."""
    import yaml

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("the file does not contain an engine design")
    if "base" in data:
        raise ValueError("this file inherits from another file (`base:`) — import the resolved "
                         "design instead (config_resolved.yaml in any report folder)")
    refs = [k for k, v in data.items() if isinstance(v, str) and v.endswith((".yaml", ".yml"))]
    if refs:
        raise ValueError(f"this file references other files ({', '.join(refs)}) — import a resolved design")
    data.pop("config_hash", None)
    result = validate(data)
    return {"design": data, "valid": result["ok"], "errors": result["errors"]}


def dump_yaml(design: dict[str, Any]) -> str:
    import yaml

    clean = {k: v for k, v in design.items() if v is not None and k != "config_hash"}
    header = ("# RESA engine design — run with: python -m resa run <this file>\n")
    return header + yaml.safe_dump(clean, sort_keys=False, allow_unicode=True)


# --------------------------------------------------------------------------- #
# first channel layout
# --------------------------------------------------------------------------- #
def _regen_block(cfg: EngineConfig, side: str, fluid: str, count: int, height: Any, rib: float,
                 wall: float, p_in: float, T_in: float, material: str,
                 stop_x: Optional[float]) -> dict[str, Any]:
    hydrogen = "hydrogen" in fluid.lower()
    return {
        "meta": {"name": f"{cfg.engine}_channels", "description": "", "version": "1"},
        "contour": {"type": "from_engine"},
        "channels": {
            "count": count, "inner_wall_thickness": wall, "height": height,
            "rib": {"mode": "fixed_width", "width": rib},
            "helix": {"profile": 0, "interp": "pchip", "handedness": "right"},
            "min_channel_width": 0.3e-3, "stop_x": stop_x,
        },
        "geometry": {"n_stations": 240, "width_reference": "mid_height"},
        "solver": {
            "enabled": True, "coolant": fluid, "coolant_side": side,
            "coolant_correlation": "taylor" if hydrogen else "auto",
            "inlet": {"pressure_bar": p_in, "temperature_K": T_in, "location": "nozzle_end"},
            "wall": {"material": material}, "roughness": 8e-6,
            "skirt": {"enabled": True, "emissivity": 0.8, "T_env_K": 300},
        },
        "export": {"stl": True, "step": False},
    }


def suggest_channels(design: dict[str, Any], max_trials: int = 8) -> dict[str, Any]:
    """A first regen layout that works for this design.

    Sizing rules (a starting point, meant to be refined):
      * coolant: the fuel when CoolProp can model it, else the oxidizer
      * pitch ~ 7 % of the throat diameter (0.9..3 mm), rib 40 % of it
      * throat channel height from a target coolant velocity: 30 m/s for
        liquids, Mach 0.15 for gases (CoolProp density at the inlet); the
        nozzle side tapers to hold the flow area, the chamber side keeps at
        least the throat height (lower flux, long channels)
      * copper alloy above ~8 MW/m2 peak flux, else Inconel 718
      * channels end at area ratio 15 on large nozzles (radiation-cooled beyond)
    Candidates (deeper channels, higher inlet pressure) are then solved at
    preview resolution; the first that stays under the wall limit with feed
    margin wins, else the best feasible one.
    """
    from CoolProp.CoolProp import PropsSI

    from resa.regen_channels.coolant import Coolant

    cfg, res = _pipeline(design)
    tc = res.thrust_chamber
    pr = cfg.propellants
    e = heatflux.estimate(cfg, res, 800.0)

    def modelled(fluid: str) -> bool:
        try:
            Coolant(fluid)
            return True
        except Exception:
            return False

    # coolant: a propellant that can absorb the heat load without boiling. A
    # side that would boil at the default pressure but has a reachable critical
    # pressure runs supercritical (e.g. N2O at ~80 bar).
    p_default = float(round(1.8 * tc.pc_bar + 10.0))
    options = []
    for side_, fluid_, mdot_, T_ in (("fuel", pr.fuel, tc.mdot_fuel_kg_s, pr.fuel_temp_K),
                                     ("oxidizer", pr.oxidizer, tc.mdot_ox_kg_s, pr.ox_temp_K)):
        if not modelled(fluid_):
            continue
        p_ = p_default
        cap = heatflux._coolant_capacity(side_, fluid_, mdot_, T_, p_, e.Q_total_W)
        p_crit = Coolant(fluid_).p_crit / 1e5
        if cap.boils and p_crit < 3.0 * p_default:
            p_ = float(round(max(p_default, 1.15 * p_crit)))
            cap = heatflux._coolant_capacity(side_, fluid_, mdot_, T_, p_, e.Q_total_W)
        ok = cap.outlet_T_K is not None and not cap.boils and cap.outlet_T_K < 900.0
        options.append((ok, side_ == "fuel", side_, fluid_, mdot_, T_, p_))
    if not options:
        raise ValueError("neither propellant has a fluid-property model — regenerative cooling "
                         "cannot be analysed for this propellant pair")
    options.sort(reverse=True)            # capable first, fuel preferred

    rt = tc.throat_radius_m
    dt = 2 * rt
    q_max = e.q_max_W_m2
    copper = q_max > 8e6
    material = ("GRCop-42" if dt < 0.02 else "CuCrZr") if copper else "Inconel 718"
    wall = (0.5e-3 if dt < 0.02 else 0.7e-3) if copper else (0.5e-3 if dt < 0.02 else 0.8e-3)
    pitch = float(np.clip(0.07 * dt, 0.9e-3, 3e-3))
    rib0 = max(0.4 * pitch, 0.4e-3)
    count = max(8, int(round(2 * np.pi * (rt + wall) / pitch)))
    h_lo, h_hi = (0.3e-3 if dt < 0.02 else 0.4e-3), max(4e-3, 0.3 * dt)

    cont = res.contour
    i = np.argsort(cont.x_m)
    x, r = cont.x_m[i], cont.r_m[i]
    it = int(np.argmin(r))
    stop_x = None
    if tc.eps > 15.0:
        k15 = it + int(np.argmin(np.abs((r[it:] / rt) ** 2 - 15.0)))
        stop_x = round(float(x[k15]), 4)
    x_end = stop_x if stop_x is not None else float(x[-1])

    def width_at(k: int, rib: float) -> float:
        return max(2 * np.pi * (r[k] + wall) / count - rib, 1e-4)

    def profile(h_t: float, rib: float):
        picks = sorted({0, it // 2, int(0.85 * it), it})
        nz = [k for k in range(it, len(x)) if x[k] <= x_end + 1e-9]
        picks = sorted(set(picks) | {nz[len(nz) // 3], nz[2 * len(nz) // 3], nz[-1]})
        area_t = count * width_at(it, rib) * h_t
        pts = []
        for k in picks:
            lo = h_t if k < it else max(h_lo, 0.7 * h_t)
            h_k = float(np.clip(area_t / (count * width_at(k, rib)), lo, min(h_hi, 2.5 * h_t)))
            pts.append([round(float(x[k]), 4), round(h_k, 5)])
        flat = max(p[1] for p in pts) - min(p[1] for p in pts) < 0.05e-3
        return round(h_t, 5) if flat else pts

    def search(side: str, fluid: str, mdot: float, T_in: float, p0: float):
        """Adaptive trials for one coolant -> (best or None, trials)."""
        cp_name = Coolant(fluid).cp_name
        try:
            rho = PropsSI("D", "T", T_in, "P", p0 * 1e5, cp_name)
            a = PropsSI("A", "T", T_in, "P", p0 * 1e5, cp_name)
        except ValueError:
            rho, a = 800.0, 1000.0
        v_target = 30.0 if rho > 40.0 else 0.15 * a     # liquids (incl. LH2) vs gases
        rib = rib0
        h_t = float(np.clip(mdot / (rho * v_target) / (count * width_at(it, rib)), h_lo, h_hi))
        p_in, p_cap = p0, float(round(2.5 * p0))
        best, trials = None, []
        for _ in range(max_trials):
            block = _regen_block(cfg, side, fluid, count, profile(h_t, rib), round(rib, 5), wall,
                                 p_in, T_in, material, stop_x)
            d = {**_strip_offdesign(design), "regen": block, "cooling": None}
            d["propellants"] = {**design["propellants"], "fuel_temp_source": "input",
                                "ox_temp_source": "input"}
            out = cooling(d, "preview")
            row = {"side": side, "height_throat_m": round(h_t, 6), "rib_m": round(rib, 6),
                   "inlet_p_bar": p_in, "ok": bool(out.get("ok"))}
            trials.append(row)
            if not out.get("ok"):
                # pressure collapse / choking: open the channels, raise the pressure
                row["error"] = str(out.get("error", ""))[:160]
                h_t, p_in = min(h_t * 1.4, h_hi), min(float(round(p_in * 1.3)), p_cap)
                continue
            sm = out["summary"]
            margin = sm.get("wall_margin_K")
            margin = -1e9 if margin is None else margin
            feed = sm.get("feed_margin_bar")
            feed_ok = feed is None or feed >= 0.0
            dp = sm.get("dp_bar") or 0.0
            row.update(T_wall_max_K=sm.get("T_wall_max_K"), margin_K=margin, dp_bar=dp,
                       feed_margin_bar=feed)
            score = (feed_ok, min(margin, 150.0), -dp)
            if best is None or score > best[0]:
                best = (score, block, h_t, p_in, rib, v_target)
            if feed_ok and margin >= 0:
                break
            if not feed_ok:
                if p_in >= p_cap:
                    h_t = min(h_t * 1.3, h_hi)
                p_in = min(float(round(p_in - (feed or 0.0) * 1.3 + 5.0)), p_cap)
            elif h_t > h_lo * 1.01:
                # too hot: faster coolant in shallower channels
                h_t = max(h_t * 0.72, h_lo)
                p_in = min(float(round(p_in + 1.5 * dp)), p_cap)
            elif rib < 0.65 * pitch:
                # already shallow: narrower channels (wider ribs) for more speed
                rib = min(rib * 1.35, 0.65 * pitch)
                p_in = min(float(round(p_in + dp)), p_cap)
            else:
                break
        return best, trials

    trials: list[dict] = []
    best = None
    for capable, _fuel, side_, fluid_, mdot_, T_, p_ in options:
        b, t = search(side_, fluid_, mdot_, T_, p_)
        trials += t
        if b is not None and (best is None or b[0] > best[0][0]):
            best = (b, side_, fluid_, T_)
        if best is not None and best[0][0][0] and best[0][0][1] >= 0:
            break

    notes: list[str] = []
    if best is None:
        _, _, side, fluid, _, T_in, p_in = options[0]
        h_t, rib, v_target = h_lo * 2, rib0, 30.0
        block = _regen_block(cfg, side, fluid, count, profile(h_t, rib), round(rib, 5), wall,
                             p_in, T_in, material, stop_x)
        notes.append("no trial layout solved cleanly — this starting point needs manual changes "
                     "(larger channels, higher inlet pressure or the other propellant as coolant)")
    else:
        ((feed_ok, margin, _), block, h_t, p_in, rib, v_target), side, fluid, T_in = best
        if margin < 0:
            notes.append(f"the best of {len(trials)} trial layouts still runs the wall "
                         f"{-margin:.0f} K above its limit — consider film cooling, a lower chamber "
                         "pressure or a calibrated heat-transfer factor")
        if not feed_ok:
            notes.append("coolant pressure drop exceeds the feed budget — raise the inlet pressure")
    width = width_at(it, rib)
    if side == "oxidizer":
        notes.append(f"cooling with the oxidizer ({fluid}): the fuel flow cannot carry the heat load")
    if stop_x is not None:
        notes.append(f"channels end at area ratio 15 (x = {stop_x*1e3:.0f} mm); the nozzle "
                     "extension beyond is radiation-cooled")
    return {
        "ok": True, "side": side, "coolant": fluid, "count": count,
        "height_m": block["channels"]["height"], "height_throat_m": round(h_t, 5),
        "rib_m": round(rib, 5), "wall_m": wall, "inlet_p_bar": p_in, "inlet_T_K": T_in,
        "material": material, "channel_width_m": width, "target_velocity_m_s": v_target,
        "q_max_W_m2": q_max, "stop_x": stop_x, "regen": block, "trials": trials, "notes": notes,
    }
