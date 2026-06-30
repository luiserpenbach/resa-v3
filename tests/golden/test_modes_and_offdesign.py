"""Round-trip (design->analyze), optimization paths, off-design physics."""
import numpy as np
import pytest

from resa.config.loader import load_config
from resa.pipeline import run, run_file
from tests.golden.helpers import CI_E2_ASBUILT, CI_E2_DESIGN


@pytest.fixture(scope="module")
def design():
    return run_file(CI_E2_DESIGN)


@pytest.fixture(scope="module")
def asbuilt():
    return run_file(CI_E2_ASBUILT)


def test_roundtrip_design_analyze(design, asbuilt):
    """Designed geometry + designed mdots fed to analyze mode must reproduce
    the design Pc and thrust (the two modes share the same physics)."""
    d, a = design.thrust_chamber, asbuilt.thrust_chamber
    assert a.pc_bar == pytest.approx(d.pc_bar, rel=2e-4)
    assert a.thrust_N == pytest.approx(d.thrust_N, rel=2e-4)
    assert a.isp_s == pytest.approx(d.isp_s, rel=2e-4)


def test_analyze_provenance(asbuilt):
    p = asbuilt.thrust_chamber.provenance
    assert p["thrust"] == "calculated" and p["pc"] == "calculated"
    assert p["mdot"] == "input" and p["geometry"] == "input"


def test_optimum_of(design):
    cfg = load_config(CI_E2_DESIGN)
    op = cfg.operating_point.model_copy(update={"of_ratio": None})
    r = run(cfg.model_copy(update={"operating_point": op, "offdesign": None}))
    tc = r.thrust_chamber
    assert "optimized" in tc.provenance["of_ratio"]
    assert tc.isp_s >= design.thrust_chamber.isp_s          # optimum beats fixed
    assert 4.0 <= tc.of_ratio <= 5.5                       # near c* peak (N2O/EtOH)


def test_optimum_eps_is_adapted(design):
    cfg = load_config(CI_E2_DESIGN)
    op = cfg.operating_point.model_copy(update={"eps": None, "pe_bar": None})
    r = run(cfg.model_copy(update={"operating_point": op, "offdesign": None}))
    tc = r.thrust_chamber
    assert "optimized" in tc.provenance["eps"]
    assert tc.pe_bar == pytest.approx(1.01325, rel=1e-3)    # pe = p_amb
    assert tc.isp_s >= design.thrust_chamber.isp_s


def test_ox_throttle_physics(design):
    """Fuel constant; thrust & Pc monotonic with ox flow; nominal recovered."""
    s = design.offdesign.ox_throttle
    assert np.allclose(s.mdot_fuel_kg_s, s.mdot_fuel_kg_s[0])
    assert np.all(np.diff(s.thrust_N) > 0)
    assert np.all(np.diff(s.pc_bar) > 0)
    d = design.thrust_chamber
    i = np.argmin(np.abs(s.mdot_ox_kg_s - d.mdot_ox_kg_s))
    assert s.thrust_N[i] == pytest.approx(d.thrust_N, rel=2e-2)


def test_of_sweep_constant_mdot(design):
    s = design.offdesign.of_sweep
    assert np.allclose(s.mdot_total_kg_s, s.mdot_total_kg_s[0], rtol=1e-9)
    # Isp has an interior maximum near the c* peak
    i = int(s.isp_s.argmax())
    assert 0 < i < len(s.of) - 1
    assert 4.0 <= s.of[i] <= 5.5


def test_envelope_shape(design):
    e = design.offdesign.envelope
    assert e.isp_s.shape == (len(e.of), len(e.throttle_frac))
    # Pc rises with throttle at any O/F row
    assert np.all(np.diff(e.pc_bar, axis=1) > 0)
