"""Golden regression: EX15 design (offline combustion table)."""
import pytest

from resa.pipeline import run_file
from tests.golden.helpers import CI_EX15_DESIGN, load_expected

EXP = load_expected("ex15_design")


@pytest.fixture(scope="module")
def result():
    return run_file(CI_EX15_DESIGN)


def test_thrust_closes(result):
    assert EXP["thrust_closes_N"] == pytest.approx(result.thrust_chamber.thrust_N, rel=1e-6)


def test_of_split(result):
    tc = result.thrust_chamber
    assert tc.mdot_ox_kg_s / tc.mdot_fuel_kg_s == pytest.approx(EXP["of_ratio"], rel=1e-9)


def test_golden_scalars(result):
    tc = result.thrust_chamber
    assert tc.eps == pytest.approx(EXP["eps"], rel=1e-9)
    assert tc.throat_radius_m * 1e3 == pytest.approx(EXP["throat_r_mm"], abs=0.02)
    assert tc.isp_s == pytest.approx(EXP["isp_s"], abs=0.2)
    assert tc.cf == pytest.approx(EXP["cf"], abs=0.002)


def test_provenance_design(result):
    p = result.thrust_chamber.provenance
    exp = EXP["provenance"]
    assert p["eps"] == exp["eps"]
    assert p["of_ratio"] == exp["of_ratio"]
