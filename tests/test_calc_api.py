"""Stateless /api/calc endpoints (Studio calculations)."""
import copy

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from resa.config.loader import load_config  # noqa: E402
from resa_studio.api.main import app  # noqa: E402

client = TestClient(app)


def _design(path="configs/ci/e2_c1_design_regen.yaml"):
    return load_config(path).model_dump(mode="json", exclude={"config_hash"})


@pytest.fixture(scope="module")
def regen_design():
    return _design()


def test_catalog():
    r = client.get("/api/calc/catalog")
    assert r.status_code == 200
    j = r.json()
    assert {p["id"] for p in j["propellants"]} >= {"lox", "n2o", "ethanol", "lh2"}
    assert any(m["name"] == "GRCop-42" for m in j["materials"])
    assert "cea" in j["chemistry"]


def test_validate_reports_paths(regen_design):
    bad = copy.deepcopy(regen_design)
    bad["operating_point"]["pc_bar"] = -3
    j = client.post("/api/calc/validate", json={"design": bad}).json()
    assert j["ok"] is False
    assert j["errors"][0]["path"] == ["operating_point", "pc_bar"]
    assert client.post("/api/calc/validate", json={"design": regen_design}).json()["ok"]


def test_performance(regen_design):
    r = client.post("/api/calc/performance", json={"design": regen_design})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["performance"]["thrust_N"] == pytest.approx(regen_design["operating_point"]["thrust_N"], rel=1e-3)
    assert j["geometry"]["throat_diameter_m"] > 0
    assert len(j["contour"]["x_m"]) == len(j["contour"]["r_m"]) > 20
    assert all({"area", "message"} <= set(w) for w in j["warnings"])


def test_performance_invalid_design_is_422(regen_design):
    bad = copy.deepcopy(regen_design)
    bad["chamber"]["contraction_ratio"] = 0.5
    r = client.post("/api/calc/performance", json={"design": bad})
    assert r.status_code == 422
    assert r.json()["detail"][0]["path"] == ["chamber", "contraction_ratio"]


def test_heat_flux(regen_design):
    j = client.post("/api/calc/heat-flux", json={"design": regen_design, "wall_temp_K": 800}).json()
    s = j["summary"]
    assert s["q_max_W_m2"] > 1e6
    assert s["Q_total_W"] == pytest.approx(s["Q_chamber_W"] + s["Q_nozzle_W"], rel=1e-9)
    # peak flux sits near the throat
    assert abs(s["x_q_max_m"]) < 0.02
    assert {c["side"] for c in j["coolant_capacity"]} == {"fuel", "oxidizer"}


def test_cooling_preview_has_ph_data(regen_design):
    r = client.post("/api/calc/cooling", json={"design": regen_design, "fidelity": "preview"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"], j
    assert j["summary"]["T_wall_max_K"] > 300
    assert len(j["path"]["h_kJ_kg"]) == len(j["path"]["p_bar"]) == len(j["path"]["x_m"]) + 1
    assert j["ph"]["dome"]["h_liquid_kJ_kg"] and j["ph"]["isotherms"]
    n = len(j["profiles"]["x_m"])
    assert all(len(v) == n for v in j["profiles"].values())


def test_cooling_without_channels(regen_design):
    d = copy.deepcopy(regen_design)
    d["regen"] = None
    j = client.post("/api/calc/cooling", json={"design": d}).json()
    assert j["ok"] is False and "no cooling channels" in j["error"]


def test_geometry_and_stl(regen_design):
    j = client.post("/api/calc/cooling/geometry", json={"design": regen_design}).json()
    assert j["section"]["station"]["n_channels"] == regen_design["regen"]["channels"]["count"]
    assert j["assembly"]["profile"]["x_m"]
    r = client.post("/api/calc/cooling/export", json={"design": regen_design, "format": "stl"})
    assert r.status_code == 200 and len(r.content) > 84


def test_trade_study(regen_design):
    j = client.post("/api/calc/trade-study", json={
        "design": regen_design, "parameter": "operating_point.pc_bar", "values": [20, 25, 30]}).json()
    rows = j["rows"]
    assert [r["value"] for r in rows] == [20, 25, 30]
    assert all(r["ok"] for r in rows)
    # higher chamber pressure -> smaller throat, higher peak heat flux
    assert rows[0]["throat_diameter_m"] > rows[-1]["throat_diameter_m"]
    assert rows[0]["q_max_W_m2"] < rows[-1]["q_max_W_m2"]


def test_trade_study_rejects_unknown_parameter(regen_design):
    r = client.post("/api/calc/trade-study", json={
        "design": regen_design, "parameter": "engine", "values": [1, 2]})
    assert r.status_code == 400


def test_offdesign():
    d = _design("configs/ci/e2_c1_design.yaml")
    if not d.get("offdesign"):
        d["offdesign"] = {"of_sweep": {"of_range": [3.0, 6.0], "n": 6}}
    j = client.post("/api/calc/offdesign", json={"design": d}).json()
    assert j["ok"]
    assert j["offdesign"]


def test_design_without_cooling_block_runs(regen_design):
    d = copy.deepcopy(regen_design)
    d.pop("cooling", None)
    r = client.post("/api/calc/performance", json={"design": d})
    assert r.status_code == 200, r.text


def test_layout_assistant_returns_a_valid_regen_block(regen_design):
    d = copy.deepcopy(regen_design)
    d["regen"] = None
    r = client.post("/api/calc/cooling/suggest", json={"design": d})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["side"] in ("fuel", "oxidizer")
    assert j["trials"] and all("inlet_p_bar" in t for t in j["trials"])
    d["regen"] = j["regen"]
    assert client.post("/api/calc/validate", json={"design": d}).json()["ok"]
    cool = client.post("/api/calc/cooling", json={"design": d}).json()
    assert cool["ok"], cool


def test_hopelessly_overexpanded_nozzle_says_so(regen_design):
    d = copy.deepcopy(regen_design)
    d["regen"] = None
    d["operating_point"].update(eps=500.0, pe_bar=None, p_amb_bar=1.01325)
    r = client.post("/api/calc/performance", json={"design": d})
    assert r.status_code == 400
    assert "over-expanded" in r.json()["detail"]
