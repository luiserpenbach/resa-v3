"""Test suite: profiles, contour, layout geometry, mesh integrity, solver smoke."""
import numpy as np
import pytest

from resa.regen_channels.config import RegenConfig
from resa.regen_channels.contour import build_contour
from resa.regen_channels.layout import ChannelLayout
from resa.regen_channels.mesh import build_channel_mesh, channel_corner_curves
from resa.regen_channels.profiles import Profile1D

BASE = dict(
    meta={"name": "test"},
    contour={"type": "parametric", "parametric": dict(
        chamber_radius=40e-3, chamber_length=70e-3, throat_radius=14.8e-3,
        expansion_ratio=4.0, nozzle_type="bell")},
    channels={"count": 40, "inner_wall_thickness": 0.8e-3, "height": 2e-3,
              "rib": {"mode": "fixed_width", "width": 1e-3},
              "helix": {"profile": 0.0}},
    geometry={"n_stations": 120},
    solver={"enabled": False},
)


def make(over=None):
    import copy
    raw = copy.deepcopy(BASE)
    for k, v in (over or {}).items():
        d = raw
        ks = k.split(".")
        for kk in ks[:-1]:
            d = d[kk]
        d[ks[-1]] = v
    cfg = RegenConfig.model_validate(raw)
    return cfg, ChannelLayout(build_contour(cfg.contour), cfg)


def test_profile_constant_and_breakpoints():
    p = Profile1D(2e-3)
    assert np.allclose(p(np.linspace(0, 1, 5)), 2e-3)
    q = Profile1D([[0.0, 1.0], [1.0, 3.0]])
    assert np.isclose(q(0.5), 2.0, atol=0.3)
    assert np.isclose(q(-5.0), 1.0) and np.isclose(q(5.0), 3.0)


def test_contour_throat_and_monotone_segments():
    cfg, lay = make()
    assert np.isclose(lay.r_throat, 14.8e-3, rtol=1e-3)
    c = lay.contour
    assert np.isclose(c.r(c.x_min), 40e-3, rtol=1e-6)
    assert np.isclose(c.r(c.x_max), 14.8e-3 * 2.0, rtol=2e-2)


def test_straight_channels_have_zero_wrap():
    _, lay = make()
    assert np.allclose(lay.theta, 0.0)
    assert np.allclose(lay.dl, lay.ds)


def test_fixed_rib_width_follows_radius():
    _, lay = make()
    pitch = 2 * np.pi * lay.r_ref / 40
    assert np.allclose(lay.w, pitch - 1e-3)


def test_spiral_wrap_and_path_lengthening():
    _, lay = make({"channels.helix": {"profile": 30.0}})
    assert lay.theta[-1] > 0.5
    assert np.all(lay.dl >= lay.ds - 1e-12)
    assert np.allclose(lay.dl, lay.ds / np.cos(np.radians(30)), rtol=1e-9)


def test_helix_switching_profile():
    _, lay = make({"channels.helix": {
        "profile": [[0.0, 0.0], [0.08, 0.0], [0.11, 30.0],
                    [0.14, 30.0], [0.17, 0.0]], "interp": "linear"}})
    b = np.degrees(lay.beta)
    assert abs(b[0]) < 1e-9 and abs(b[-1]) < 1e-9
    assert b.max() > 29.0


def test_min_width_guard_raises():
    with pytest.raises(ValueError):
        make({"channels.count": 120})


def test_variable_height_and_rib():
    _, lay = make({"channels.height": [[0.0, 3e-3], [0.2, 1.5e-3]],
                   "channels.rib": {"mode": "variable",
                                    "width": [[0.0, 1.5e-3], [0.2, 0.8e-3]]}})
    assert lay.h[0] > lay.h[-1]
    assert lay.t_rib[0] > lay.t_rib[-1]


def test_start_stop_trim():
    _, lay = make({"channels.start_x": 0.02, "channels.stop_x": 0.15})
    assert lay.x[0] >= 0.02 - 1e-12 and lay.x[-1] <= 0.15 + 1e-12


def test_mesh_watertight_and_width():
    _, lay = make({"channels.helix": {"profile": 25.0}})
    v, f, _ = build_channel_mesh(lay, [0])
    assert np.all(np.isfinite(v))
    e = np.sort(np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    assert np.all(counts == 2)
    c = channel_corner_curves(lay, 0)
    d = np.linalg.norm(c["floor_L"] - c["floor_R"], axis=1)
    assert np.max(np.abs(d - lay.w) / lay.w) < 0.06


def test_solver_smoke_energy_closure():
    cfg, lay = make({"geometry.n_stations": 60, "solver": {
        "enabled": True, "coolant": "NitrousOxide",
        "inlet": {"pressure_bar": 60.0, "temperature_K": 278.0,
                  "location": "nozzle_end"}}})
    from resa.regen_channels.solver import RegenSolver
    sol = RegenSolver(lay, cfg)
    df = sol.solve()
    assert (df.T_wall_hot_K > df.T_wall_cold_K).all()
    assert (df.T_wall_cold_K > df.T_cool_K - 1e-6).all()
    x_peak = df.x_m[df.q_w_W_m2.idxmax()]
    assert abs(x_peak - lay.x_throat) < 0.02
    a = df.attrs
    assert abs(a["energy_balance_kW"]) < 1e-6
    assert abs(a["dh_kJ_kg"] * 1e3 * sol.mdot_ch - df.Q_cell_W.sum()) / df.Q_cell_W.sum() < 0.02
    assert df.attrs["outlet_p_bar"] < 60.0


def test_figure_coolant_path_smoke():
    from resa.regen_channels.viz import figure_coolant_path
    cfg, lay = make({"geometry.n_stations": 40, "solver": {
        "enabled": True, "coolant": "NitrousOxide",
        "inlet": {"pressure_bar": 60.0, "temperature_K": 278.0,
                  "location": "nozzle_end"}}})
    from resa.regen_channels.solver import RegenSolver
    df = RegenSolver(lay, cfg).solve()
    fig = figure_coolant_path(df, cfg.solver.coolant)
    assert len(fig.data) >= 4


def test_diff_configs_and_layouts():
    from resa.regen_channels.diff import diff_configs, diff_layouts
    cfg_a, lay_a = make()
    cfg_b, lay_b = make({"channels.count": 44,
                         "channels.helix": {"profile": 20.0}})
    rows = diff_configs(cfg_a, cfg_b)
    keys = [r[0] for r in rows]
    assert "channels.count" in keys
    scalar_rows, profile_rows, _ = diff_layouts(lay_a, lay_b)
    changed = {r[0]: r for r in scalar_rows if not r[3]}
    assert "channel count" in changed and "total wrap [deg]" in changed
    beta = [p for p in profile_rows if p[0] == "helix angle"][0]
    assert abs(beta[2] - 20.0) < 0.5


def test_diff_identical_is_clean():
    from resa.regen_channels.diff import diff_configs, diff_layouts
    cfg, lay = make()
    assert diff_configs(cfg, cfg) == []
    scalar_rows, profile_rows, _ = diff_layouts(lay, lay)
    assert all(r[3] for r in scalar_rows)
    assert all(p[2] < 1e-12 for p in profile_rows)
