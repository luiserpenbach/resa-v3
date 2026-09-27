"""NASA CEA backend (combustion.backend: cea) against rocketcea reference values."""
import builtins

import pytest

pytest.importorskip("cea")

from resa.config.schema import CombustionConfig, PropellantConfig  # noqa: E402
from resa.properties import combustion  # noqa: E402
from resa.properties.nasa_cea import NasaCeaModel, resolve_propellant  # noqa: E402

N2O_ETH = dict(name="N2O/Ethanol", oxidizer="NitrousOxide", fuel="Ethanol",
               ox_temp_K=285, fuel_temp_K=293.15, cea_oxidizer="N2O", cea_fuel="C2H5OH")
LOX_LH2 = dict(name="LOX/LH2", oxidizer="Oxygen", fuel="Hydrogen", ox_temp_K=90,
               fuel_temp_K=20.3, cea_oxidizer="LOX", cea_fuel="LH2")
GOX_GH2 = dict(name="GOX/GH2", oxidizer="Oxygen", fuel="Hydrogen", ox_temp_K=250,
               fuel_temp_K=400, ox_phase="gas", fuel_phase="gas",
               cea_oxidizer="O2", cea_fuel="H2")


def _model(prop, flow, delivery=False, pc=25.0):
    comb = CombustionConfig(backend="cea", nozzle_flow=flow,
                            use_delivery_temperatures=delivery)
    return combustion.build_model(PropellantConfig(**prop), comb, pc_hint_bar=pc)


def _isp_vac(m, of, pc, eps):
    return m.nozzle(of, pc, eps).cf_vac * m.at(of, pc).cstar_ideal_m_s / 9.80665


# rocketcea 1.2.3 values at the same points
@pytest.mark.parametrize("prop,of,pc,eps,flow,isp_ref,delivery", [
    (N2O_ETH, 4.0, 25.0, 4.0, "equilibrium", 257.35, False),
    (N2O_ETH, 4.0, 25.0, 4.0, "frozen", 251.52, False),
    (N2O_ETH, 4.0, 25.0, 4.0, "frozen_at_throat", 254.83, False),
    (LOX_LH2, 6.0, 70.0, 40.0, "equilibrium", 451.7, False),
    (LOX_LH2, 6.0, 70.0, 40.0, "frozen", 430.5, False),
    (GOX_GH2, 2.5, 6.0, 80.0, "frozen", 479.0, True),
    (GOX_GH2, 2.5, 6.0, 80.0, "frozen_at_throat", 481.6, True),
])
def test_vacuum_isp_matches_rocketcea(prop, of, pc, eps, flow, isp_ref, delivery):
    m = _model(prop, flow, delivery, pc)
    assert isinstance(m, NasaCeaModel)
    assert _isp_vac(m, of, pc, eps) == pytest.approx(isp_ref, rel=2e-3)


def test_chamber_state_and_transport():
    m = _model(N2O_ETH, "equilibrium")
    c = m.at(4.0, 25.0)
    assert c.cstar_ideal_m_s == pytest.approx(1577.6, rel=1e-3)
    assert c.tc_K == pytest.approx(3054.7, rel=1e-3)
    assert c.gamma == pytest.approx(1.1659, rel=1e-3)
    assert c.mw_kg_kmol == pytest.approx(24.668, rel=1e-3)
    t = m.transport(4.0, 25.0)
    assert t["mu_Pa_s"] == pytest.approx(9.495e-5, rel=5e-3)
    assert t["pr_frozen"] == pytest.approx(0.660, rel=5e-3)
    assert t["cp_frozen_J_kgK"] * t["mu_Pa_s"] / t["k_frozen_W_mK"] == pytest.approx(
        t["pr_frozen"], rel=1e-3)


@pytest.mark.parametrize("flow", ["equilibrium", "frozen", "frozen_at_throat"])
def test_exit_pressure_roundtrip(flow):
    m = _model(N2O_ETH, flow)
    ns = m.nozzle(4.0, 25.0, 6.0)
    eps, ns2 = m.eps_for_pe(4.0, 25.0, ns.pe_over_pc * 25.0)
    assert eps == pytest.approx(6.0, rel=1e-4)
    assert ns2.cf_vac == pytest.approx(ns.cf_vac, rel=1e-4)


def test_frozen_band_ordering():
    ref = _model(N2O_ETH, "equilibrium").reference(4.0, 25.0, 8.0)
    assert ref["frozen"] < ref["frozen_at_throat"] < ref["equilibrium"]


def test_propellant_aliases():
    assert resolve_propellant("LOX")[0].key == "oxygen"
    assert resolve_propellant(None, "NitrousOxide")[0].key == "nitrousoxide"
    assert resolve_propellant("GH2") == (resolve_propellant("Hydrogen")[0], "gas")
    with pytest.raises(ValueError, match="unknown propellant"):
        resolve_propellant("unobtainium")


def test_rocketcea_configs_fall_back_to_nasa_cea(monkeypatch):
    real_import = builtins.__import__

    def no_rocketcea(name, *a, **kw):
        if name == "rocketcea" or name.startswith("rocketcea."):
            raise ImportError("no rocketcea")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_rocketcea)
    comb = CombustionConfig(backend="rocketcea", nozzle_flow="frozen")
    m = combustion.build_model(PropellantConfig(**N2O_ETH), comb)
    assert isinstance(m, NasaCeaModel)
    assert "rocketcea is not installed" in m.note
    assert _isp_vac(m, 4.0, 25.0, 4.0) == pytest.approx(251.52, rel=2e-3)
