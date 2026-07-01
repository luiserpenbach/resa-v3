"""RESA Studio API tests."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from resa_studio.api.main import app

CI_CONFIG = "configs/ci/ex15_design.yaml"


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_config_list(client):
    r = client.get("/api/config/list")
    assert r.status_code == 200
    paths = {item["path"] for item in r.json()}
    assert "configs/projects/ex15/design.yaml" in paths
    assert all("configs/projects/" in p for p in paths)


def test_projects_list(client):
    r = client.get("/api/projects/list")
    assert r.status_code == 200
    projects = r.json()
    assert isinstance(projects, list)
    slugs = {p["slug"] for p in projects}
    assert "ex15" in slugs
    assert "e2_c1" in slugs
    ex15 = next(p for p in projects if p["slug"] == "ex15")
    assert any(c["name"] == "design" for c in ex15["configs"])


def test_create_project_and_config(client):
    from resa_studio.settings import REPO_ROOT

    slug = "studio_test_proj"
    proj_dir = REPO_ROOT / "configs" / "projects" / slug
    try:
        r = client.post(
            "/api/projects/create",
            json={"name": "Studio Test", "slug": slug, "description": "temp"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["slug"] == slug
        assert (proj_dir / "project.yaml").is_file()
        assert body["primary_config"] == f"{slug}.yaml"
        assert (proj_dir / f"{slug}.yaml").is_file()
        assert not (proj_dir / "design.yaml").exists()

        r_valid = client.post(
            "/api/config/validate/path",
            json={"config_path": f"configs/projects/{slug}/{slug}.yaml"},
        )
        assert r_valid.status_code == 200
        assert r_valid.json()["ok"] is True

        r2 = client.post(
            f"/api/projects/{slug}/configs",
            json={"name": "variant", "mode": "design"},
        )
        assert r2.status_code == 200
        assert (proj_dir / "variant.yaml").is_file()
    finally:
        if proj_dir.is_dir():
            import shutil
            shutil.rmtree(proj_dir)



def test_validate_path(client):
    r = client.post("/api/config/validate/path", json={"config_path": CI_CONFIG})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["engine"] == "EX15"
    assert body["mode"] == "design"
    assert len(body["config_hash"]) == 12


def test_run_fast(client):
    r = client.post("/api/runs/fast", json={"config_path": CI_CONFIG})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "fast"
    assert body["engine"] == "EX15"
    assert body["summary"]["thrust_N"] > 0
    assert body["summary"]["isp_s"] > 0
    assert isinstance(body["provenance"], dict)


def test_list_runs(client):
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_run_not_found(client):
    r = client.get("/api/runs/NOENGINE/deadbeefcafe")
    assert r.status_code == 404


def test_resolve_config(client):
    r = client.get("/api/config/resolve", params={"config_path": CI_CONFIG})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "EX15"
    assert body["mode"] == "design"
    assert body["config"]["operating_point"]["thrust_N"] > 0
    assert isinstance(body["config"]["propellants"], dict)
    assert len(body["config_hash"]) == 12
    assert body["writable"] is False
    assert body["is_override"] is False
    assert body["save_path"] == CI_CONFIG


def test_resolve_spark50_config(client):
    path = "configs/projects/spark-50/spark-50.yaml"
    r = client.get("/api/config/resolve", params={"config_path": path})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "SPARK-50"
    assert body["config"]["propellants"]["name"] == "H2/GOX"
    assert body["config"]["operating_point"]["thrust_N"] == 50
    assert body["writable"] is True


def test_resolve_config_post(client):
    r = client.post("/api/config/resolve/path", json={"config_path": CI_CONFIG})
    assert r.status_code == 200
    assert r.json()["engine"] == "EX15"


def test_validate_dict(client):
    resolved = client.get("/api/config/resolve", params={"config_path": CI_CONFIG}).json()
    cfg = dict(resolved["config"])
    cfg["operating_point"] = dict(cfg["operating_point"])
    cfg["operating_point"]["thrust_N"] = 16000
    r = client.post("/api/config/validate", json={"config": cfg})
    assert r.status_code == 200
    assert r.json()["engine"] == "EX15"


def test_run_fast_inline_config(client):
    resolved = client.get("/api/config/resolve", params={"config_path": CI_CONFIG}).json()
    r = client.post("/api/runs/fast", json={"config": resolved["config"]})
    assert r.status_code == 200
    assert r.json()["summary"]["thrust_N"] > 0


def test_get_run_includes_config(client):
    pytest.importorskip("plotly")
    client.post("/api/runs/full", json={"config_path": CI_CONFIG})
    runs = client.get("/api/runs").json()
    match = next((r for r in runs if r["engine"] == "EX15"), None)
    assert match is not None
    r = client.get(f"/api/runs/{match['engine']}/{match['config_hash']}")
    assert r.status_code == 200
    body = r.json()
    assert body["config"] is not None
    assert body["analysis_mode"] == "design"
    assert body["config"]["operating_point"]["thrust_N"] > 0
    assert body["config_source"] is not None
    assert body.get("writable") is True


def test_preview_contour(client):
    resolved = client.get("/api/config/resolve", params={"config_path": CI_CONFIG}).json()
    r = client.post("/api/preview/contour", json={"config": resolved["config"]})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["contour"]["x_m"]) > 10
    assert body["summary"]["throat_radius_m"] > 0


def test_preview_cooling_section(client):
    resolved = client.get("/api/config/resolve", params={"config_path": CI_CONFIG}).json()
    r = client.post("/api/preview/cooling/section", json={"config": resolved["config"]})
    assert r.status_code == 200
    body = r.json()
    assert body["station"]["n_channels"] >= 4


def test_preview_export_stl(client):
    resolved = client.get("/api/config/resolve", params={"config_path": CI_CONFIG}).json()
    r = client.post(
        "/api/preview/cooling/export-channel",
        json={"config": resolved["config"], "channel_id": 0, "format": "stl"},
    )
    assert r.status_code == 200
    assert "stl" in r.headers["content-type"]


def test_preview_pipeline_cache(client):
    from resa_studio.adapters.preview_cache import PIPELINE_CACHE

    PIPELINE_CACHE.clear()
    resolved = client.get("/api/config/resolve", params={"config_path": CI_CONFIG}).json()
    cfg = resolved["config"]
    r1 = client.post("/api/preview/contour", json={"config": cfg})
    assert r1.status_code == 200
    stats1 = client.get("/api/preview/cache/stats").json()
    assert stats1["misses"] >= 1
    r2 = client.post("/api/preview/cooling/section", json={"config": cfg})
    assert r2.status_code == 200
    stats2 = client.get("/api/preview/cache/stats").json()
    assert stats2["hits"] >= 1
    assert stats2["entries"] >= 1


def test_preview_regen_thermal(client):
    pytest.importorskip("CoolProp")
    resolved = client.get(
        "/api/config/resolve",
        params={"config_path": "configs/ci/e2_c1_design_regen.yaml"},
    ).json()
    r = client.post("/api/preview/regen/thermal", json={"config": resolved["config"]})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    if not body.get("skipped"):
        assert body["summary"]["T_wall_max_K"] > 0
        assert len(body["profiles"]["x_m"]) > 10


def test_save_config(client):
    from resa_studio.settings import REPO_ROOT

    save_target = "configs/projects/ex15/design.yaml"
    resolved = client.get("/api/config/resolve", params={"config_path": save_target}).json()
    assert resolved["writable"] is True
    assert resolved["save_path"] == save_target
    out_file = REPO_ROOT / save_target

    cfg = dict(resolved["config"])
    cfg["operating_point"] = dict(cfg["operating_point"])
    cfg["operating_point"]["thrust_N"] = 15555

    original = out_file.read_text(encoding="utf-8")
    try:
        r = client.post(
            "/api/config/save",
            json={"config_path": save_target, "config": cfg},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["config_path"] == save_target
        saved = client.get("/api/config/resolve", params={"config_path": save_target})
        assert saved.status_code == 200
        assert saved.json()["config"]["operating_point"]["thrust_N"] == 15555
    finally:
        out_file.write_text(original, encoding="utf-8")


def test_save_preserves_yaml_file_refs(client):
    """Saving a resolved config must not inline unchanged fragment YAML paths."""
    from resa_studio.settings import REPO_ROOT

    save_target = "configs/projects/E2-1A/design.yaml"
    resolved = client.get("/api/config/resolve", params={"config_path": save_target}).json()
    out_file = REPO_ROOT / save_target
    original = out_file.read_text(encoding="utf-8")
    try:
        r = client.post(
            "/api/config/save",
            json={"config_path": save_target, "config": resolved["config"]},
        )
        assert r.status_code == 200
        saved = out_file.read_text(encoding="utf-8")
        assert "propellants: prop_n2o_ethanol.yaml" in saved
        assert "chamber: chamber_E2_TC_01.yaml" in saved
        assert "analyze_point:" not in saved
        assert "geometry:" not in saved
    finally:
        out_file.write_text(original, encoding="utf-8")


def test_campaigns_list(client):
    r = client.get("/api/campaigns/list")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    paths = {item["path"] for item in items}
    assert "campaigns/ci_golden.yaml" in paths


def test_compare_configs(client):
    resolved = client.get("/api/config/resolve", params={"config_path": CI_CONFIG}).json()
    cfg_a = dict(resolved["config"])
    cfg_b = dict(resolved["config"])
    cfg_b["operating_point"] = dict(cfg_b["operating_point"])
    cfg_b["operating_point"]["thrust_N"] = 14000
    r = client.post(
        "/api/compare/configs",
        json={"config_a": cfg_a, "config_b": cfg_b},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["config_diff"], list)
    keys = {row["key"] for row in body["config_diff"]}
    assert any("thrust_N" in k for k in keys)


def test_compare_runs_not_found(client):
    r = client.post(
        "/api/compare/runs",
        json={
            "engine_a": "NOENGINE",
            "config_hash_a": "deadbeefcafe",
            "engine_b": "NOENGINE",
            "config_hash_b": "cafebabefeed",
        },
    )
    assert r.status_code == 404


def test_run_fast_includes_offdesign_when_configured(client):
    r = client.post("/api/runs/fast", json={"config_path": CI_CONFIG})
    assert r.status_code == 200
    body = r.json()
    od = body.get("result", {}).get("offdesign")
    if od is not None:
        assert "ox_throttle" in od or "of_sweep" in od or "envelope" in od


def test_config_schema(client):
    r = client.get("/api/config/schema")
    assert r.status_code == 200
    body = r.json()
    assert "properties" in body
    assert "operating_point" in body["properties"]


def test_full_report_results_include_offdesign(client):
    pytest.importorskip("plotly")
    r = client.post("/api/runs/full", json={"config_path": CI_CONFIG})
    assert r.status_code == 200
    body = r.json()
    od = body.get("result", {}).get("offdesign") or body.get("results", {}).get("offdesign")
    assert od is not None
    assert od.get("ox_throttle") or od.get("of_sweep") or od.get("envelope")
