"""Uncertainty bands (eta_cstar ± tol) and report-folder diff."""
import numpy as np
import pytest

from resa.config.loader import load_config
from resa.pipeline import run, run_file
from resa.reporting.diff import diff_dicts, diff_folders
from resa.reporting.report import write_report
from tests.golden.helpers import (
    CI_E2_ASBUILT,
    CI_E2_DESIGN,
    CI_E2_HF02,
    load_expected,
)

EXP = load_expected("e2_c1_design")


@pytest.fixture(scope="module")
def design():
    return run_file(CI_E2_DESIGN)


@pytest.fixture(scope="module")
def asbuilt():
    return run_file(CI_E2_ASBUILT)


def test_design_bands_isp_and_mdot(design):
    u = design.uncertainty
    tc = design.thrust_chamber
    assert u is not None and u.eta_tol == pytest.approx(EXP["uncertainty"]["eta_tol"])
    # lower eta -> lower Isp but MORE propellant for the same thrust
    assert u.tc_lo.isp_s < tc.isp_s < u.tc_hi.isp_s
    assert u.tc_lo.mdot_total_kg_s > tc.mdot_total_kg_s > u.tc_hi.mdot_total_kg_s
    # thrust/pc are design inputs -> identical across the band
    assert u.tc_lo.thrust_N == u.tc_hi.thrust_N == tc.thrust_N
    assert u.tc_lo.pc_bar == u.tc_hi.pc_bar == tc.pc_bar


def test_analyze_bands_pc_thrust(asbuilt):
    u = asbuilt.uncertainty
    tc = asbuilt.thrust_chamber
    # measured flows fixed -> lower eta means lower pc, thrust, isp
    assert u.tc_lo.pc_bar < tc.pc_bar < u.tc_hi.pc_bar
    assert u.tc_lo.thrust_N < tc.thrust_N < u.tc_hi.thrust_N
    assert np.isclose(u.tc_lo.mdot_total_kg_s, tc.mdot_total_kg_s)


def test_sweep_bands_bracket_nominal(design):
    u, od = design.uncertainty, design.offdesign
    s, lo, hi = od.ox_throttle, u.od_lo.ox_throttle, u.od_hi.ox_throttle
    assert len(lo.of) == len(s.of) == len(hi.of)
    assert np.all(lo.thrust_N < s.thrust_N)
    assert np.all(s.thrust_N < hi.thrust_N)


def test_diff_dicts_basics():
    a = {"x": {"pc": 25.0, "name": "A"}, "same": 1.0}
    b = {"x": {"pc": 27.5, "name": "B"}, "same": 1.0}
    rows = diff_dicts(a, b)
    keys = [r[0] for r in rows]
    assert "x.pc" in keys and "x.name" in keys and "same" not in keys
    pc_row = rows[keys.index("x.pc")]
    assert "+10.00%" in pc_row[3]


def test_diff_folders_end_to_end(tmp_path):
    cfg_a = load_config(CI_E2_ASBUILT)
    cfg_b = load_config(CI_E2_HF02)
    da, _ = write_report(run(cfg_a), cfg_a, "a", out_root=tmp_path)
    db, _ = write_report(run(cfg_b), cfg_b, "b", out_root=tmp_path)
    out = diff_folders(da, db)
    assert "INPUT changes" in out and "RESULT changes" in out
    assert "geometry.throat_diameter_m" in out      # the input that changed
    assert "thrust_chamber.pc_bar" in out           # the consequence
    assert "uncertainty.low" not in out             # band internals filtered
