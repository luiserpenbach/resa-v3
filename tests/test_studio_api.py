"""RESA Studio API tests."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

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
    # Run snapshots are read-only: save_config only accepts configs/projects/.
    assert body.get("writable") is False


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


def test_run_meta_and_baseline(tmp_path):
    """Run labels/notes persist; baseline pin round-trips and marks listings."""
    from resa_studio.adapters.run_service import RunService

    out_root = tmp_path / "out"
    svc = RunService(out_root=out_root)
    out = svc.run_full(config_path=CI_CONFIG)
    engine, config_hash = out.config.engine, out.config.config_hash

    # meta merge + clear
    svc.set_run_meta(engine, config_hash, label="taller channels", note="cand 3")
    svc.set_run_meta(engine, config_hash, note="")           # clears note only
    runs = svc.list_runs()
    assert runs[0]["label"] == "taller channels"
    assert runs[0]["note"] is None
    assert runs[0]["pc_bar"] is not None                     # KPI columns present
    assert runs[0]["is_baseline"] is False

    # baseline pin
    svc.set_baseline(engine, config_hash)
    assert svc.get_baseline() == {"engine": engine, "config_hash": config_hash}
    assert svc.list_runs()[0]["is_baseline"] is True
    loaded = svc.load_existing(engine, config_hash)
    assert loaded["is_baseline"] is True
    assert loaded["label"] == "taller channels"

    # clear pin
    svc.set_baseline(None, None)
    assert svc.get_baseline() is None

    # unknown run rejected
    with pytest.raises(FileNotFoundError):
        svc.set_run_meta("NOPE", "deadbeefcafe", label="x")
    with pytest.raises(FileNotFoundError):
        svc.set_baseline("NOPE", "deadbeefcafe")


def test_run_meta_and_baseline_api(client):
    """API surface for labels + baseline."""
    r = client.get("/api/runs/baseline")
    assert r.status_code == 200
    r = client.post(
        "/api/runs/NOENGINE/deadbeefcafe/meta", json={"label": "x"}
    )
    assert r.status_code == 404
    r = client.post(
        "/api/runs/baseline", json={"engine": "NOENGINE", "config_hash": "dead"}
    )
    assert r.status_code == 404


def test_preview_cache_slow_run_still_fresh(monkeypatch):
    """An entry from a pipeline slower than the TTL must be fresh on arrival."""
    import time as _time

    from resa_studio.adapters import preview_cache as pc

    calls = {"n": 0}

    def fake_run(cfg):
        calls["n"] += 1
        _time.sleep(0.15)
        return "result"

    monkeypatch.setattr(pc, "pipeline_run", fake_run)
    cache = pc.PipelinePreviewCache(ttl_s=0.1)
    data = {"engine": "X"}
    cache.get_or_run(data, lambda d: "cfg")
    cache.get_or_run(data, lambda d: "cfg")   # within TTL of *completion*
    assert calls["n"] == 1


def test_preview_cache_waiters_do_not_stampede(monkeypatch):
    """Waiters unblocked by the leader reuse its result, run nothing."""
    import threading

    from resa_studio.adapters import preview_cache as pc

    calls = {"n": 0}
    release = threading.Event()

    def fake_run(cfg):
        calls["n"] += 1
        release.wait(timeout=5.0)
        return "result"

    monkeypatch.setattr(pc, "pipeline_run", fake_run)
    cache = pc.PipelinePreviewCache(ttl_s=60.0)
    data = {"engine": "X"}
    results = []

    def worker():
        results.append(cache.get_or_run(data, lambda d: "cfg"))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    threads[0].start()
    while calls["n"] == 0:      # leader inside fake_run
        pass
    for t in threads[1:]:
        t.start()
    release.set()
    for t in threads:
        t.join(timeout=5.0)
    assert calls["n"] == 1
    assert len(results) == 4
    assert all(r == ("cfg", "result") for r in results)


def test_preview_cache_failed_leader_single_retry(monkeypatch):
    """After a leader fails, wakers re-contend: one retry, not a herd."""
    import threading

    from resa_studio.adapters import preview_cache as pc

    calls = {"n": 0}
    release = threading.Event()
    concurrent = {"now": 0, "max": 0}
    guard = threading.Lock()

    def fake_run(cfg):
        with guard:
            calls["n"] += 1
            concurrent["now"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["now"])
        try:
            if calls["n"] == 1:
                release.wait(timeout=5.0)
                raise RuntimeError("leader dies")
            return "result"
        finally:
            with guard:
                concurrent["now"] -= 1

    monkeypatch.setattr(pc, "pipeline_run", fake_run)
    cache = pc.PipelinePreviewCache(ttl_s=60.0)
    data = {"engine": "X"}
    outcomes = []

    def worker():
        try:
            outcomes.append(cache.get_or_run(data, lambda d: "cfg"))
        except RuntimeError:
            outcomes.append("error")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    threads[0].start()
    while calls["n"] == 0:
        pass
    for t in threads[1:]:
        t.start()
    release.set()
    for t in threads:
        t.join(timeout=5.0)
    assert outcomes.count("error") == 1          # only the failed leader errors
    assert outcomes.count(("cfg", "result")) == 3
    assert concurrent["max"] == 1                # never more than one run at once


def test_relocated_out_root_outside_repo(tmp_path):
    """RESA_OUT_ROOT outside the repo must not 500 the run endpoints."""
    from resa_studio.adapters.config_service import ConfigService
    from resa_studio.adapters.run_service import RunService

    out_root = tmp_path / "external-out"
    out_root.mkdir()
    svc = RunService(out_root=out_root)
    assert svc.list_runs() == []

    out = svc.run_full(config_path=CI_CONFIG)
    assert out.outdir is not None
    assert out.outdir.is_relative_to(out_root)

    runs = svc.list_runs()
    assert len(runs) == 1
    # identifier falls back to an absolute path and stays loadable
    outdir_id = runs[0]["outdir"]
    assert Path(outdir_id).is_absolute()
    snapshot = Path(outdir_id) / "config_resolved.yaml"
    cs = ConfigService(out_root=out_root)
    resolved = cs.resolve_path(snapshot)
    assert resolved["writable"] is False

    loaded = svc.load_existing(runs[0]["engine"], runs[0]["config_hash"])
    assert loaded is not None
    assert loaded["config"] is not None


def test_relocated_projects_root_outside_repo(tmp_path):
    """RESA_PROJECTS_ROOT outside the repo: configs load, save, stay writable."""
    import shutil

    from resa_studio.adapters.config_service import ConfigService

    projects_root = tmp_path / "external-projects"
    shutil.copytree(
        Path("configs/projects/ex15"), projects_root / "ex15",
    )
    # external project needs its shared fragments reachable — inline them
    cfg_path = projects_root / "ex15" / "design.yaml"
    from resa.config.loader import load_resolved_dict

    data = load_resolved_dict(Path("configs/projects/ex15/design.yaml"))
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    cs = ConfigService(projects_root=projects_root)
    resolved = cs.resolve_path(cfg_path)
    assert resolved["writable"] is True
    body = dict(resolved["config"])
    body["operating_point"] = dict(body["operating_point"])
    body["operating_point"]["thrust_N"] = 16161
    saved = cs.save_config(resolved["save_path"], body)
    assert saved["ok"] is True
    assert cs.resolve_path(cfg_path)["config"]["operating_point"]["thrust_N"] == 16161


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
        # margin contract for the margin plot
        s = body["summary"]
        assert s["wall_limit_K"] > 0
        assert s["min_margin_K"] == pytest.approx(
            s["wall_limit_K"] - s["T_wall_max_K"], abs=0.2)
        prof = body["profiles"]
        assert len(prof["margin_K"]) == len(prof["x_m"])
        assert len(prof["T_cool_K"]) == len(prof["x_m"])
        assert min(prof["margin_K"]) == pytest.approx(s["min_margin_K"], abs=0.2)


def test_preview_regen_thermal_fidelity(client):
    pytest.importorskip("CoolProp")
    resolved = client.get(
        "/api/config/resolve",
        params={"config_path": "configs/ci/e2_c1_design_regen.yaml"},
    ).json()
    coarse = client.post(
        "/api/preview/regen/thermal",
        json={"config": resolved["config"], "fidelity": "preview"},
    ).json()
    full = client.post(
        "/api/preview/regen/thermal",
        json={"config": resolved["config"], "fidelity": "full"},
    ).json()
    assert coarse["ok"] and full["ok"]
    assert full["preview_stations"] == full["full_stations"]
    assert coarse["preview_stations"] < full["full_stations"]
    assert len(full["profiles"]["x_m"]) == full["full_stations"]


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
        saved_doc = yaml.safe_load(saved)
        assert "analyze_point" not in saved_doc
        assert "geometry" not in saved_doc
    finally:
        out_file.write_text(original, encoding="utf-8")


def test_save_overlay_edit_wins_over_explicit_null(client):
    """Editing a key that is explicitly null on disk must keep the edit."""
    from resa_studio.settings import REPO_ROOT

    save_target = "configs/projects/E2-1A/asbuilt.yaml"
    resolved = client.get("/api/config/resolve", params={"config_path": save_target}).json()
    out_file = REPO_ROOT / save_target
    original = out_file.read_text(encoding="utf-8")

    # asbuilt.yaml has `operating_point: null` — switch it back to design mode.
    cfg = dict(resolved["config"])
    cfg["operating_point"] = {
        "thrust_N": 2400, "pc_bar": 26.0, "of_ratio": 4.0, "eta_cstar": 0.93,
    }
    cfg["analyze_point"] = None
    cfg["geometry"] = None
    try:
        r = client.post(
            "/api/config/save",
            json={"config_path": save_target, "config": cfg},
        )
        assert r.status_code == 200
        saved_doc = yaml.safe_load(out_file.read_text(encoding="utf-8"))
        assert saved_doc["operating_point"] is not None
        assert saved_doc["operating_point"]["thrust_N"] == 2400
        re_resolved = client.get(
            "/api/config/resolve", params={"config_path": save_target}
        ).json()
        assert re_resolved["config"]["operating_point"]["thrust_N"] == 2400
    finally:
        out_file.write_text(original, encoding="utf-8")


def test_save_overlay_keeps_ref_equal_to_inherited(client):
    """A fragment ref whose content equals the inherited value must survive a save."""
    from resa_studio.settings import REPO_ROOT

    thin = REPO_ROOT / "configs/projects/E2-1A/_test_thin.yaml"
    thin.write_text(
        "base: design.yaml\nchamber: chamber_E2_TC_01.yaml\n", encoding="utf-8"
    )
    rel = "configs/projects/E2-1A/_test_thin.yaml"
    try:
        resolved = client.get("/api/config/resolve", params={"config_path": rel}).json()
        r = client.post(
            "/api/config/save",
            json={"config_path": rel, "config": resolved["config"]},
        )
        assert r.status_code == 200
        saved = thin.read_text(encoding="utf-8")
        assert "chamber: chamber_E2_TC_01.yaml" in saved
    finally:
        thin.unlink(missing_ok=True)


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
