"""Physics fixes and additions: CEA nozzle modes, delivery-temperature cards,
transport sync, Bartz curvature / effective c*, coolant-side inference and
flow guard, laminar/Taylor correlations, materials + stress, radiation
skirt, feed budget, loss estimate, coupling loops.

rocketcea-dependent tests skip when the Fortran backend is not installed
(CI installs only the table backend)."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from resa.config.loader import load_config, load_resolved_dict
from resa.config.schema import EngineConfig
from resa.pipeline import run
from resa.regen.integration import (
    infer_coolant_side,
    prepare_regen_config,
    run_regen,
    solve_regen,
)
from resa.regen_channels import correlations as co
from resa.regen_channels import materials
from resa.regen_channels.config import HotGasCfg, RegenConfig
from resa.regen_channels.hotgas import HotGas
from tests.golden.helpers import CI_E2_DESIGN

CI_E2_REGEN = "configs/ci/e2_c1_design_regen.yaml"
SPARK50 = "configs/projects/spark-50/spark-50.yaml"


def _regen_dict(path=CI_E2_REGEN, **over):
    d = load_resolved_dict(path)
    for key, val in over.items():
        cur = d
        parts = key.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = val
    return d


@pytest.fixture(scope="module")
def e2_regen_result():
    cfg = load_config(CI_E2_REGEN)
    return cfg, run(cfg)


# ---------------------------------------------------------------- coolant side
def test_coolant_side_inferred_from_species(e2_regen_result):
    cfg, res = e2_regen_result
    prop = cfg.propellants
    assert infer_coolant_side("NitrousOxide", None, prop) == "oxidizer"
    assert infer_coolant_side("N2O", None, prop) == "oxidizer"
    assert infer_coolant_side("Ethanol", None, prop) == "fuel"
    assert infer_coolant_side("ethanol", "fuel", prop) == "fuel"
    with pytest.raises(ValueError, match="neither the fuel"):
        infer_coolant_side("Water", None, prop)


def test_coolant_side_conflict_with_species_raises(e2_regen_result):
    cfg, res = e2_regen_result
    regen = cfg.regen.model_copy(update={
        "solver": cfg.regen.solver.model_copy(update={"coolant": "Ethanol",
                                                     "coolant_side": "oxidizer"})})
    with pytest.raises(ValueError, match="fix coolant_side"):
        prepare_regen_config(regen, res.thrust_chamber, res.combustion, cfg.chamber,
                             propellants=cfg.propellants)


def test_coolant_flow_cannot_exceed_side_flow(e2_regen_result):
    cfg, res = e2_regen_result
    regen = cfg.regen.model_copy(update={
        "solver": cfg.regen.solver.model_copy(update={"coolant": "Ethanol",
                                                     "coolant_side": None,
                                                     "coolant_fraction": 0.5})})
    # fuel is 1/5 of the flow at O/F 4; half the total flow of ethanol is impossible
    with pytest.raises(ValueError, match="exceeds the engine fuel flow"):
        prepare_regen_config(regen, res.thrust_chamber, res.combustion, cfg.chamber,
                             propellants=cfg.propellants)


def test_inferred_fuel_side_uses_fuel_flow(e2_regen_result):
    cfg, res = e2_regen_result
    regen = cfg.regen.model_copy(update={
        "solver": cfg.regen.solver.model_copy(update={"coolant": "Ethanol",
                                                     "coolant_side": None})})
    prepared = prepare_regen_config(regen, res.thrust_chamber, res.combustion,
                                    cfg.chamber, propellants=cfg.propellants)
    assert prepared.solver.coolant_side == "fuel"
    assert prepared.solver.mdot_total == pytest.approx(res.thrust_chamber.mdot_fuel_kg_s)


def test_standalone_without_side_or_mdot_raises():
    from resa.regen_channels.contour import build_contour
    from resa.regen_channels.layout import ChannelLayout
    from resa.regen_channels.solver import RegenSolver
    raw = dict(
        contour={"type": "parametric", "parametric": dict(
            chamber_radius=40e-3, chamber_length=70e-3, throat_radius=14.8e-3,
            expansion_ratio=4.0, nozzle_type="bell")},
        channels={"count": 40, "inner_wall_thickness": 0.8e-3, "height": 2e-3,
                  "rib": {"mode": "fixed_width", "width": 1e-3}},
        geometry={"n_stations": 40},
        solver={"enabled": True, "coolant": "NitrousOxide"},
    )
    cfg = RegenConfig.model_validate(raw)
    lay = ChannelLayout(build_contour(cfg.contour), cfg)
    with pytest.raises(ValueError, match="coolant_side"):
        RegenSolver(lay, cfg)


# ---------------------------------------------------------------- hot gas
def test_bartz_curvature_and_effective_cstar_synced(e2_regen_result):
    cfg, res = e2_regen_result
    prepared = prepare_regen_config(cfg.regen, res.thrust_chamber, res.combustion,
                                    cfg.chamber, propellants=cfg.propellants)
    hg = prepared.solver.hot_gas
    assert hg.c_star_m_s == pytest.approx(res.thrust_chamber.cstar_eff_m_s)
    assert hg.throat_curvature_factor == pytest.approx(0.5 * (1.5 + 0.382))
    lay, df, sol = solve_regen(prepared, res.contour)
    Rt = res.thrust_chamber.throat_radius_m
    assert sol.hot.r_curv == pytest.approx(0.941 * Rt, rel=1e-3)
    # the old code used 0.94 * Dt (twice the intended value)
    assert sol.hot.r_curv < 1.0 * Rt
    assert df.attrs["wall_solve_fallbacks"] == 0
    assert df.attrs["coolant_side"] == "oxidizer"


def test_hot_gas_fallback_properties_flagged_without_transport(e2_regen_result):
    cfg, res = e2_regen_result
    # CI table has no transport columns -> Eucken / default mu fallbacks
    assert not res.combustion.has_transport
    prepared = prepare_regen_config(cfg.regen, res.thrust_chamber, res.combustion,
                                    cfg.chamber, propellants=cfg.propellants)
    _, df, sol = solve_regen(prepared, res.contour)
    assert sol.hot.uses_fallback_properties
    assert "Eucken" in df.attrs["hot_gas_property_note"]


def test_table_transport_columns_sync_into_bartz():
    d = _regen_dict()
    t = d["combustion"]["table"]
    n = len(t["of"])
    t["mu_pa_s"] = [8.5e-5] * n
    t["pr"] = [0.62] * n
    t["cp_J_kgK"] = [2600.0] * n
    cfg = EngineConfig.model_validate(d)
    res = run(cfg)
    assert res.combustion.has_transport
    prepared = prepare_regen_config(cfg.regen, res.thrust_chamber, res.combustion,
                                    cfg.chamber, propellants=cfg.propellants)
    assert prepared.solver.hot_gas.pr == pytest.approx(0.62)
    assert prepared.solver.hot_gas.mu_pa_s == pytest.approx(8.5e-5)
    assert prepared.solver.hot_gas.cp_J_kgK == pytest.approx(2600.0)
    _, df, sol = solve_regen(prepared, res.contour)
    assert not sol.hot.uses_fallback_properties


def test_bartz_band_orders_wall_temperatures(e2_regen_result, tmp_path):
    cfg, res = e2_regen_result
    chamber = cfg.chamber.model_copy(update={"bartz_correction_tol": 0.2})
    regen = cfg.regen.model_copy(update={"export": cfg.regen.export.model_copy(
        update={"stl": False, "step": False, "html_3d": False, "html_plots": False})})
    prepared = prepare_regen_config(regen, res.thrust_chamber, res.combustion,
                                    chamber, propellants=cfg.propellants)
    rg = run_regen(prepared, res.contour, tmp_path)
    assert rg.band is not None
    lo, hi = rg.band["lo"]["T_wall_max_K"], rg.band["hi"]["T_wall_max_K"]
    nom = rg.results.T_wall_hot_K.max()
    assert lo < nom < hi
    assert rg.summary()["T_wall_max_hi_K"] == hi


# ---------------------------------------------------------------- correlations
def test_laminar_rect_nu_and_transition_blend():
    assert co.laminar_nu_rect(1.0) == pytest.approx(3.61)
    assert co.laminar_nu_rect(0.0) == pytest.approx(8.23)
    assert co.laminar_nu_rect(0.25) == pytest.approx(5.33)
    f = co.churchill_f(3000.0, 1e-3)
    nu_lam = co.nu_single_phase(2000.0, 0.7, f, 0.5)
    nu_mid = co.nu_single_phase(3000.0, 0.7, f, 0.5)
    nu_turb = co.nu_single_phase(4000.0, 0.7, f, 0.5)
    assert nu_lam == pytest.approx(co.laminar_nu_rect(0.5))
    assert nu_lam <= nu_mid <= nu_turb
    assert co.nu_single_phase(20000.0, 0.7, co.churchill_f(20000.0, 1e-3), 1.0) > 40


def test_taylor_nu_decreases_with_wall_to_bulk_ratio():
    nu1 = co.taylor_nu(20000.0, 0.7, 300.0, 300.0, 50.0)
    nu3 = co.taylor_nu(20000.0, 0.7, 900.0, 300.0, 50.0)
    assert nu3 < nu1
    assert nu1 == pytest.approx(0.023 * 20000 ** 0.8 * 0.7 ** 0.4)


def test_materials_database_and_wall_limits():
    assert materials.resolve("Inconel 718").key == "in718"
    assert materials.resolve("IN718") is materials.resolve("inconel718")
    assert materials.resolve("CuCrZr").max_service_T_K < materials.resolve("C-103").max_service_T_K
    assert materials.resolve("unobtainium") is None
    m = materials.resolve("in718")
    assert m.k(300) == pytest.approx(11.4)
    assert m.yield_MPa(1100) < m.yield_MPa(300)


def test_stress_formulas():
    s = co.thermal_stress_MPa(200.0, 13e-6, 10e6, 0.5e-3, 17.0, 0.29)
    assert s == pytest.approx(200e9 * 13e-6 * 10e6 * 0.5e-3 / (2 * 0.71 * 17.0) / 1e6)
    assert co.pressure_bending_stress_MPa(50e5, 1.2e-3, 0.5e-3) == pytest.approx(50e5 * (2.4 ** 2) / 2 / 1e6)


def test_regen_results_carry_stress_and_mach_columns(e2_regen_result):
    cfg, res = e2_regen_result
    prepared = prepare_regen_config(cfg.regen, res.thrust_chamber, res.combustion,
                                    cfg.chamber, propellants=cfg.propellants)
    _, df, _ = solve_regen(prepared, res.contour)
    assert df.attrs["stress_checked"]
    assert np.isfinite(df.sigma_total_MPa).all()
    assert df.attrs["sigma_max_MPa"] > 0
    assert 0 < df.attrs["coolant_mach_max"] < 1
    assert df.attrs["wall_limit_K"] == pytest.approx(1200.0)   # explicit in regen.yaml


def test_wall_limit_defaults_to_material_database(e2_regen_result):
    cfg, res = e2_regen_result
    wall = cfg.regen.solver.wall.model_copy(update={"max_wall_temp_K": None,
                                                    "material": "CuCrZr",
                                                    "conductivity": None})
    regen = cfg.regen.model_copy(update={"solver": cfg.regen.solver.model_copy(update={"wall": wall})})
    prepared = prepare_regen_config(regen, res.thrust_chamber, res.combustion,
                                    cfg.chamber, propellants=cfg.propellants)
    _, df, sol = solve_regen(prepared, res.contour)
    assert df.attrs["wall_limit_K"] == pytest.approx(materials.resolve("CuCrZr").max_service_T_K)
    assert sol.k_wall(400.0) > 250.0


# ---------------------------------------------------------------- skirt / feed
def test_radiation_skirt_temperature_falls_with_area_ratio():
    from resa.regen_channels.skirt import solve_radiation_skirt
    hot = HotGas(HotGasCfg(pc_bar=7.0, tc_K=3000.0, gamma=1.2, mol_mass_kg_kmol=12.0,
                           c_star_m_s=2400.0, bartz_correction=1.0), np.pi * 3.4e-3 ** 2,
                 6.8e-3, 3.2e-3)
    x = np.linspace(0.01, 0.08, 30)
    r = 3.4e-3 * np.sqrt(np.linspace(4.0, 80.0, 30))
    df = solve_radiation_skirt(hot, x, r, 0.0, 0.8, 300.0)
    assert np.all(np.diff(df.T_wall_K) < 0)
    assert 1000 < df.attrs["T_wall_exit_K"] < df.attrs["T_wall_max_K"] < 2600
    assert df.attrs["Q_radiated_kW"] > 0


def test_skirt_solved_when_channels_stop_before_exit(e2_regen_result, tmp_path):
    cfg, res = e2_regen_result
    regen = cfg.regen.model_copy(update={
        "channels": cfg.regen.channels.model_copy(update={"stop_x": 0.015}),
        "solver": cfg.regen.solver.model_copy(update={
            "skirt": cfg.regen.solver.skirt.model_copy(update={"material": "CuCrZr"})}),
        "export": cfg.regen.export.model_copy(
            update={"stl": False, "step": False, "html_3d": False, "html_plots": False})})
    prepared = prepare_regen_config(regen, res.thrust_chamber, res.combustion,
                                    cfg.chamber, propellants=cfg.propellants)
    rg = run_regen(prepared, res.contour, tmp_path)
    assert rg.skirt is not None
    assert rg.skirt.x_m.iloc[0] == pytest.approx(0.015, abs=1e-6)
    assert any("radiation-cooled skirt" in w for w in rg.warnings)   # CuCrZr limit exceeded
    assert any(f.endswith("_skirt.csv") for f in rg.files)
    assert "skirt_T_max_K" in rg.summary()


def test_feed_pressure_budget_warning(e2_regen_result, tmp_path):
    cfg, res = e2_regen_result
    # a 90 bar inlet leaves ~78 bar at the outlet: demand pc x 4 to force a shortfall
    regen = cfg.regen.model_copy(update={
        "solver": cfg.regen.solver.model_copy(update={"injector_dp_fraction": 3.0}),
        "export": cfg.regen.export.model_copy(
            update={"stl": False, "step": False, "html_3d": False, "html_plots": False})})
    prepared = prepare_regen_config(regen, res.thrust_chamber, res.combustion,
                                    cfg.chamber, propellants=cfg.propellants)
    rg = run_regen(prepared, res.contour, tmp_path)
    assert rg.feed_budget is not None
    assert rg.feed_budget["required_p_bar"] == pytest.approx(25.0 * 4.0)
    assert rg.feed_budget["margin_bar"] < 0
    assert any("below" in w and "raise inlet pressure" in w for w in rg.warnings)
    assert rg.summary()["feed_margin_bar"] == rg.feed_budget["margin_bar"]


def test_coolant_pressure_collapse_gives_clear_error(e2_regen_result):
    cfg, res = e2_regen_result
    inlet = cfg.regen.solver.inlet.model_copy(update={"pressure_bar": 40.0})
    regen = cfg.regen.model_copy(update={
        "solver": cfg.regen.solver.model_copy(update={"inlet": inlet})})
    prepared = prepare_regen_config(regen, res.thrust_chamber, res.combustion,
                                    cfg.chamber, propellants=cfg.propellants)
    with pytest.raises(ValueError, match="coolant state failed"):
        solve_regen(prepared, res.contour)


# ---------------------------------------------------------------- losses / kernel
def test_loss_estimate_scales_with_engine_size():
    cfg = load_config(CI_E2_DESIGN)
    big = run(cfg.model_copy(update={"offdesign": None}))
    op = cfg.operating_point.model_copy(update={"thrust_N": 50.0})
    small = run(cfg.model_copy(update={"operating_point": op, "offdesign": None}))
    assert big.losses.re_throat > 1e5 > small.losses.re_throat
    assert small.losses.bl_loss_fraction > big.losses.bl_loss_fraction
    assert 0 < small.losses.eta_cf_estimate < 1
    assert any("throat Reynolds" in w for w in small.warnings)
    assert not any("throat Reynolds" in w for w in big.warnings)


def test_eta_cf_estimate_loop_converges():
    cfg = load_config(CI_E2_DESIGN)
    op = cfg.operating_point.model_copy(update={"eta_cf_source": "estimate", "eta_cf": 1.0})
    res = run(cfg.model_copy(update={"operating_point": op, "offdesign": None}))
    tc = res.thrust_chamber
    assert res.coupling is not None and res.coupling.converged
    assert tc.eta_cf == pytest.approx(res.losses.eta_cf_estimate, abs=1e-3)
    assert tc.eta_cf < 1.0
    assert tc.provenance["eta_cf"].startswith("estimated")
    assert tc.thrust_N == pytest.approx(2200.0)


def test_regen_outlet_coupling_loop_table_backend():
    d = _regen_dict(**{"propellants.ox_temp_source": "regen_outlet"})
    cfg = EngineConfig.model_validate(d)
    res = run(cfg)
    cp = res.coupling
    assert cp is not None and cp.converged and cp.coupled_side == "oxidizer"
    assert cp.ox_temp_K == pytest.approx(cp.regen_outlet_T_K)
    assert cp.ox_temp_K > cfg.propellants.ox_temp_K


def test_coupling_requires_regen_and_matching_side():
    with pytest.raises(ValueError, match="needs a regen block"):
        EngineConfig.model_validate(
            load_resolved_dict(CI_E2_DESIGN) | {"propellants": {
                **load_resolved_dict(CI_E2_DESIGN)["propellants"], "fuel_temp_source": "regen_outlet"}})
    d = _regen_dict(**{"propellants.fuel_temp_source": "regen_outlet"})   # coolant_side: oxidizer
    with pytest.raises(ValueError, match="coolant_side"):
        EngineConfig.model_validate(d)


def test_nozzle_flow_needs_rocketcea_for_tables():
    d = load_resolved_dict(CI_E2_DESIGN)
    d["combustion"]["nozzle_flow"] = "frozen"
    with pytest.raises(ValueError, match="nozzle_flow"):
        EngineConfig.model_validate(d)
    d = load_resolved_dict(CI_E2_DESIGN)
    d["combustion"]["use_delivery_temperatures"] = True
    with pytest.raises(ValueError, match="use_delivery_temperatures"):
        EngineConfig.model_validate(d)


def test_cooling_block_mismatch_warning(e2_regen_result):
    cfg, res = e2_regen_result
    assert any("cooling block disagrees" in w for w in res.warnings)   # 40 vs 50 channels


def test_single_gamma_results_unchanged_for_table_backend(e2_regen_result):
    cfg, res = e2_regen_result
    tc = res.thrust_chamber
    assert tc.cf_source == "single_gamma"
    assert tc.isp_s == pytest.approx(215.535, abs=0.01)


# ---------------------------------------------------------------- rocketcea only
@pytest.fixture(scope="module")
def cea():
    return pytest.importorskip("rocketcea")


def test_cea_nozzle_modes_ordering(cea):
    from resa.config.schema import CombustionConfig, PropellantConfig
    from resa.properties.combustion import build_model
    prop = PropellantConfig(name="H2/GOX", oxidizer="Oxygen", fuel="Hydrogen",
                            ox_temp_K=250, fuel_temp_K=400, cea_oxidizer="O2", cea_fuel="H2")
    isp = {}
    for flow in ("single_gamma", "equilibrium", "frozen_at_throat", "frozen"):
        m = build_model(prop, CombustionConfig(backend="rocketcea", nozzle_flow=flow))
        c, ns = m.at(4.2, 7.0), m.nozzle(4.2, 7.0, 80.0)
        isp[flow] = ns.cf_vac * c.cstar_ideal_m_s / 9.80665
        assert ns.source == ("single_gamma" if flow == "single_gamma" else f"cea_{flow}")
    assert isp["single_gamma"] > isp["equilibrium"] > isp["frozen_at_throat"] > isp["frozen"]
    assert isp["equilibrium"] == pytest.approx(463.8, abs=0.5)
    assert isp["frozen"] == pytest.approx(447.9, abs=0.5)
    ref = m.reference(4.2, 7.0, 80.0)
    assert ref["equilibrium"] == pytest.approx(isp["equilibrium"], abs=0.5)


def test_cea_delivery_temperature_cards(cea):
    from resa.config.schema import CombustionConfig, PropellantConfig
    from resa.properties.combustion import build_model
    prop = PropellantConfig(name="H2/GOX", oxidizer="Oxygen", fuel="Hydrogen",
                            ox_temp_K=250, fuel_temp_K=400, cea_oxidizer="O2", cea_fuel="H2",
                            ox_phase="gas", fuel_phase="gas")
    cold = build_model(prop, CombustionConfig(backend="rocketcea")).at(4.2, 7.0)
    warm = build_model(prop, CombustionConfig(backend="rocketcea", use_delivery_temperatures=True)).at(4.2, 7.0)
    assert warm.tc_K > cold.tc_K + 100
    assert warm.cstar_ideal_m_s > cold.cstar_ideal_m_s * 1.03
    assert "400.0 K" in warm.fuel_state and "delivery" in warm.fuel_state
    # liquid reference round trip reproduces the CEA default card
    cryo = PropellantConfig(name="x", oxidizer="Oxygen", fuel="Hydrogen", ox_temp_K=90.18,
                            fuel_temp_K=20.27, cea_oxidizer="O2", cea_fuel="H2",
                            ox_phase="liquid", fuel_phase="liquid")
    rt = build_model(cryo, CombustionConfig(backend="rocketcea", use_delivery_temperatures=True)).at(4.2, 7.0)
    assert rt.tc_K == pytest.approx(cold.tc_K, abs=2.0)
    tr = build_model(prop, CombustionConfig(backend="rocketcea")).transport(4.2, 7.0)
    assert 0.5 < tr["pr_frozen"] < 0.8 and tr["cp_eq_J_kgK"] > tr["cp_frozen_J_kgK"]


def test_cea_default_state_warning(cea):
    d = load_resolved_dict(SPARK50)
    d["combustion"]["use_delivery_temperatures"] = False
    d["propellants"]["fuel_temp_source"] = "input"
    d["regen"] = None
    d["operating_point"]["eta_cf_source"] = "input"
    res = run(EngineConfig.model_validate(d))
    assert any("CEA default fuel state" in w for w in res.warnings)


def test_spark50_config_runs_with_corrected_physics(cea, tmp_path):
    from resa.regen.integration import run_regen_for_engine
    cfg = load_config(SPARK50)
    res = run(cfg)
    tc = res.thrust_chamber
    assert tc.cf_source == "cea_frozen"
    assert res.coupling is not None and res.coupling.converged
    assert res.coupling.coupled_side == "fuel"
    assert res.coupling.fuel_temp_K == pytest.approx(res.coupling.regen_outlet_T_K)
    assert tc.provenance["eta_cf"].startswith("estimated")
    assert res.nozzle_reference is not None
    assert res.combustion.has_transport
    regen = cfg.regen.model_copy(update={"export": cfg.regen.export.model_copy(
        update={"stl": False, "step": False, "html_3d": False, "html_plots": False})})
    rg = run_regen_for_engine(cfg.model_copy(update={"regen": regen}), tc, res.combustion,
                              res.contour, tmp_path)
    s = rg.summary()
    assert s["coolant_side"] == "fuel"
    assert s["mdot_coolant_kg_s"] == pytest.approx(tc.mdot_fuel_kg_s, abs=1e-6)
    assert s["outlet_T_K"] == pytest.approx(res.coupling.regen_outlet_T_K, abs=1.0)
    assert rg.band is not None and rg.feed_budget is not None
