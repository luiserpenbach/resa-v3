"""RESA regen sync opt-out flags."""
import pytest

from resa.config.loader import load_config
from resa.pipeline import run
from resa.regen.integration import prepare_regen_config
from resa.regen_channels.config import RegenConfig


def _regen_raw(**overrides):
    raw = load_config("configs/ci/e2_c1_design_regen.yaml").regen.model_dump()
    for key, val in overrides.items():
        parts = key.split(".")
        d = raw
        for p in parts[:-1]:
            d = d[p]
        d[parts[-1]] = val
    return raw


def test_sync_defaults_all_enabled():
    cfg = load_config("configs/projects/e2_c1/design_regen.yaml")
    sync = cfg.regen.sync
    assert sync.contour is True
    assert sync.hot_gas_pc_bar is True
    assert sync.mdot is True


def test_sync_opt_out_hot_gas_pc():
    cfg = load_config("configs/ci/e2_c1_design_regen.yaml")
    regen = cfg.regen.model_copy(update={
        "sync": cfg.regen.sync.model_copy(update={"hot_gas_pc_bar": False}),
        "solver": cfg.regen.solver.model_copy(update={
            "hot_gas": cfg.regen.solver.hot_gas.model_copy(update={"pc_bar": 99.0}),
        }),
    })
    res = run(cfg.model_copy(update={"regen": None}))
    prepared = prepare_regen_config(
        regen, res.thrust_chamber, res.combustion, cfg.chamber)
    assert prepared.solver.hot_gas.pc_bar == 99.0
    assert prepared.solver.hot_gas.tc_K == res.combustion.tc_K  # still synced


def test_sync_opt_out_mdot_requires_total():
    with pytest.raises(ValueError, match="mdot_total"):
        RegenConfig.model_validate(_regen_raw(**{"sync.mdot": False}))


def test_sync_mdot_uses_engine_ox_flow():
    cfg = load_config("configs/ci/e2_c1_design_regen.yaml")
    res = run(cfg.model_copy(update={"regen": None}))
    prepared = prepare_regen_config(
        cfg.regen, res.thrust_chamber, res.combustion, cfg.chamber)
    assert prepared.solver.mdot_total == pytest.approx(
        res.thrust_chamber.mdot_ox_kg_s, rel=1e-9)


def test_sync_mdot_fuel_side():
    cfg = load_config("configs/ci/e2_c1_design_regen.yaml")
    regen = cfg.regen.model_copy(update={
        "solver": cfg.regen.solver.model_copy(update={"coolant_side": "fuel"}),
    })
    res = run(cfg.model_copy(update={"regen": None}))
    prepared = prepare_regen_config(
        regen, res.thrust_chamber, res.combustion, cfg.chamber)
    assert prepared.solver.mdot_total == pytest.approx(
        res.thrust_chamber.mdot_fuel_kg_s, rel=1e-9)
