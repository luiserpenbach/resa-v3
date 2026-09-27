"""Bartz heat-flux hand calc (resa.models.heatflux)."""
import numpy as np
import pytest

from resa.config.loader import load_config
from resa.models import heatflux
from resa.pipeline import run
from resa.regen.integration import prepare_regen_config, solve_regen


@pytest.fixture(scope="module")
def case():
    cfg = load_config("configs/ci/e2_c1_design_regen.yaml")
    return cfg, run(cfg)


def test_peak_near_throat_and_totals(case):
    cfg, res = case
    e = heatflux.estimate(cfg, res, 800.0)
    assert abs(e.x_q_max_m) < 0.02
    assert e.q_max_W_m2 >= e.q_throat_W_m2 > 0
    assert e.Q_total_W == pytest.approx(e.Q_chamber_W + e.Q_nozzle_W)
    assert np.all(e.q_W_m2 >= 0)


def test_hotter_wall_takes_less_heat(case):
    cfg, res = case
    cold, hot = heatflux.estimate(cfg, res, 500.0), heatflux.estimate(cfg, res, 1200.0)
    assert hot.Q_total_W < cold.Q_total_W


def test_bartz_band_brackets_nominal(case):
    cfg, res = case
    banded = cfg.model_copy(update={"chamber": cfg.chamber.model_copy(update={"bartz_correction_tol": 0.2})})
    e = heatflux.estimate(banded, res, 800.0)
    assert np.all(e.q_lo_W_m2 <= e.q_W_m2 + 1e-9) and np.all(e.q_W_m2 <= e.q_hi_W_m2 + 1e-9)


def test_agrees_with_regen_solver_to_first_order(case):
    """Same hot-gas model: the hand calc lands near the full solve's heat load."""
    cfg, res = case
    regen = prepare_regen_config(cfg.regen, res.thrust_chamber, res.combustion, cfg.chamber,
                                 propellants=cfg.propellants)
    _, df, _ = solve_regen(regen, res.contour)
    # evaluated at the solver's wall temperature where the flux peaks
    T_peak = float(df.T_wall_hot_K.iloc[int(df.q_w_W_m2.values.argmax())])
    e = heatflux.estimate(cfg, res, T_peak)
    assert e.q_max_W_m2 == pytest.approx(df.q_w_W_m2.max(), rel=0.1)


def test_coolant_capacity_sides(case):
    cfg, res = case
    e = heatflux.estimate(cfg, res, 800.0)
    sides = {c.side: c for c in e.coolant}
    assert set(sides) == {"fuel", "oxidizer"}
    for c in sides.values():
        assert c.dh_kJ_kg == pytest.approx(e.Q_total_W / c.mdot_kg_s / 1e3)
