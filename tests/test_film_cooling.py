"""First-order film cooling model: performance bookkeeping + wall relief."""
import numpy as np
import pytest

from resa.config.loader import load_resolved_dict
from resa.config.schema import EngineConfig
from resa.pipeline import run

CI_DESIGN = "configs/ci/e2_c1_design.yaml"
CI_REGEN = "configs/ci/e2_c1_design_regen.yaml"


def _cfg(base_path, film=None, **extra):
    data = load_resolved_dict(base_path)
    if film is not None:
        data["film_cooling"] = film
    data.update(extra)
    return EngineConfig.model_validate(data)


def test_design_mode_film_bookkeeping():
    plain = run(_cfg(CI_DESIGN))
    f = 0.04            # core O/F stays inside the CI combustion table
    filmed = run(_cfg(CI_DESIGN, film={"fraction": f, "side": "fuel"}))

    fr = filmed.film
    assert fr is not None
    of = plain.thrust_chamber.of_ratio
    # core O/F shift: OF / (1 - f*(1+OF)) for a fuel-side film
    assert fr.of_overall == pytest.approx(of, rel=1e-6)
    assert fr.of_core == pytest.approx(of / (1 - f * (1 + of)), rel=1e-3)
    assert filmed.thrust_chamber.of_ratio == pytest.approx(fr.of_core, rel=1e-3)

    # thrust target met by the core; delivered Isp = core Isp * (1 - f)
    assert filmed.thrust_chamber.thrust_N == pytest.approx(
        plain.thrust_chamber.thrust_N, rel=1e-6)
    assert fr.isp_delivered_s == pytest.approx(fr.isp_core_s * (1 - f), rel=1e-3)
    assert fr.mdot_total_kg_s == pytest.approx(
        filmed.thrust_chamber.mdot_total_kg_s / (1 - f), rel=1e-4)
    assert fr.mdot_film_kg_s == pytest.approx(f * fr.mdot_total_kg_s, rel=1e-4)

    # model limitations surfaced
    assert any("film cooling" in w for w in filmed.warnings)
    # summary carries film columns
    s = filmed.summary()
    assert s["film_isp_delivered_s"] == fr.isp_delivered_s


def test_analyze_mode_film_bookkeeping():
    data = load_resolved_dict("configs/ci/e2_c1_asbuilt.yaml")
    plain = run(EngineConfig.model_validate(data))
    ap = plain.thrust_chamber
    f = 0.05
    data["film_cooling"] = {"fraction": f, "side": "fuel"}
    filmed = run(EngineConfig.model_validate(data))

    fr = filmed.film
    mdot_meas = data["analyze_point"]["mdot_ox_kg_s"] + data["analyze_point"]["mdot_fuel_kg_s"]
    assert fr.mdot_total_kg_s == pytest.approx(mdot_meas, rel=1e-4)
    # core runs leaner (fuel diverted to film) than the measured overall O/F
    assert fr.of_core > fr.of_overall
    assert fr.isp_delivered_s == pytest.approx(
        filmed.thrust_chamber.thrust_N / (mdot_meas * 9.80665), rel=1e-3)
    assert filmed.thrust_chamber.pc_bar < ap.pc_bar   # less combusting flow


def test_film_wall_relief_in_regen():
    pytest.importorskip("CoolProp")
    from resa.regen.integration import _build_contour, prepare_regen_config
    from resa.regen_channels.layout import ChannelLayout
    from resa.regen_channels.solver import RegenSolver

    def solve(film):
        cfg = _cfg(CI_REGEN, film=film)
        res = run(cfg)
        regen = prepare_regen_config(
            cfg.regen, res.thrust_chamber, res.combustion, cfg.chamber,
            film=cfg.film_cooling)
        lay = ChannelLayout(_build_contour(regen, res.contour), regen)
        return lay, RegenSolver(lay, regen).solve()

    lay0, dry = solve(None)
    lay1, wet = solve({
        "fraction": 0.06, "side": "fuel",
        "effectiveness_length_m": 0.08, "film_temp_K": 600.0,
    })
    # film must relieve the wall near the injector end and not heat anything
    x = lay1.x
    injector_zone = x < x.min() + 0.03
    assert (wet.T_wall_hot_K.to_numpy()[injector_zone]
            < dry.T_wall_hot_K.to_numpy()[injector_zone] - 5.0).all()
    assert float(wet.T_wall_hot_K.max()) <= float(dry.T_wall_hot_K.max()) + 1e-6


def test_film_validation():
    # fraction cannot exceed the donating side's share of total flow
    with pytest.raises(Exception, match="exceeds the fuel fraction"):
        _cfg(CI_DESIGN, film={"fraction": 0.4, "side": "fuel"})
    # max-Isp O/F search is not film-aware
    data = load_resolved_dict(CI_DESIGN)
    data["film_cooling"] = {"fraction": 0.05}
    data["operating_point"] = dict(data["operating_point"])
    data["operating_point"]["of_ratio"] = None
    with pytest.raises(Exception, match="explicit operating_point.of_ratio"):
        EngineConfig.model_validate(data)
