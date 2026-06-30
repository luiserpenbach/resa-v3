"""Golden regression: E2-C1 design (offline combustion table)."""
import pytest

from resa.pipeline import run_file
from tests.golden.helpers import CI_E2_DESIGN, load_expected

EXP = load_expected("e2_c1_design")


@pytest.fixture(scope="module")
def result():
    return run_file(CI_E2_DESIGN)


def test_thrust_closes(result):
    assert EXP["thrust_closes_N"] == pytest.approx(result.thrust_chamber.thrust_N, rel=1e-6)


def test_of_split(result):
    tc = result.thrust_chamber
    assert tc.mdot_ox_kg_s / tc.mdot_fuel_kg_s == pytest.approx(EXP["of_ratio"], rel=1e-9)


def test_golden_scalars(result):
    tc = result.thrust_chamber
    assert tc.throat_radius_m * 1e3 == pytest.approx(EXP["throat_r_mm"], abs=0.01)
    assert tc.isp_s == pytest.approx(EXP["isp_s"], abs=0.1)
    assert tc.cf == pytest.approx(EXP["cf"], abs=0.001)


def test_provenance_design(result):
    p = result.thrust_chamber.provenance
    exp = EXP["provenance"]
    assert p["thrust"] == exp["thrust"] and p["pc"] == exp["pc"]
    assert p["of_ratio"] == exp["of_ratio"] and p["eps"] == exp["eps"]
    assert p["mdot"] == exp["mdot"]
