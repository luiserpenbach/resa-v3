"""Contour regression: geometry invariants + L* round-trip."""
import numpy as np
import pytest

from resa.pipeline import run_file
from tests.golden.helpers import CI_E2_DESIGN, load_expected

EXP = load_expected("e2_c1_design")


@pytest.fixture(scope="module")
def result():
    return run_file(CI_E2_DESIGN)


def test_throat_is_global_min(result):
    c = result.contour
    assert c.r_m.min() == pytest.approx(c.throat_radius_m, rel=1e-6)
    i = np.argmin(c.r_m)
    assert c.x_m[i] == pytest.approx(0.0, abs=1e-6)


def test_area_at_throat_equals_At(result):
    c = result.contour
    i = np.argmin(np.abs(c.x_m))
    assert c.area_m2[i] == pytest.approx(result.thrust_chamber.throat_area_m2, rel=1e-4)


def test_divergent_monotonic(result):
    c = result.contour
    r_div = c.r_m[c.x_m >= 0]
    assert np.all(np.diff(r_div) >= -1e-9)


def test_exit_mach_matches_sizing(result):
    c = result.contour
    assert c.mach[-1] == pytest.approx(EXP["contour"]["exit_mach"], rel=1e-3)


def test_chamber_subsonic(result):
    c = result.contour
    assert c.mach[0] < 1.0


def test_lstar_roundtrip(result):
    """Volume integral of the contour from injector to throat reproduces L*."""
    c = result.contour
    At = result.thrust_chamber.throat_area_m2
    i = np.argsort(c.x_m)
    x, r = c.x_m[i], c.r_m[i]
    mask = x <= 0
    Vc = np.trapezoid(np.pi * r[mask] ** 2, x[mask])
    assert Vc / At == pytest.approx(1.2, rel=2e-2)   # config L* = 1.2 m
