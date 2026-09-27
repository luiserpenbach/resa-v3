"""Workspace store + HTTP API (FileStore, SQLite, optionally PostgreSQL)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from resa_studio.workspace import Invalid, reset_store_cache
from resa_studio.workspace.file_store import FileStore
from resa_studio.workspace.routes import router

API = "/api/workspace"
_ENV_VARS = ("RESA_WORKSPACE_DB", "DATABASE_URL", "POSTGRES_URL", "VERCEL", "RESA_WORKSPACE_DIR")
_PG_URL = os.environ.get("RESA_TEST_PG_URL")

CONFIG = {
    "engine": "TEST-1",
    "description": "test engine",
    "propellants": {"oxidizer": "NitrousOxide", "fuel": "Ethanol"},
    "chamber": {"contraction_ratio": 4.0, "l_star_m": 1.0, "n_stations": 100},
}


def _drop_pg_tables(url: str) -> None:
    import psycopg

    with psycopg.connect(url) as conn:
        conn.execute("DROP TABLE IF EXISTS resa_versions, resa_designs, resa_projects")


@pytest.fixture(params=["files", "sqlite", pytest.param("postgres", marks=pytest.mark.skipif(
    not _PG_URL, reason="RESA_TEST_PG_URL not set"))])
def backend(request, tmp_path, monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    if request.param == "files":
        monkeypatch.setenv("RESA_WORKSPACE_DIR", str(tmp_path / "ws"))
    elif request.param == "sqlite":
        monkeypatch.setenv("RESA_WORKSPACE_DB", f"sqlite:///{tmp_path / 'ws.db'}")
    else:
        _drop_pg_tables(_PG_URL)
        monkeypatch.setenv("RESA_WORKSPACE_DB", _PG_URL)
    reset_store_cache()
    yield request.param
    reset_store_cache()


@pytest.fixture
def client(backend):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _project(client, name="Test Engine", **extra):
    r = client.post(f"{API}/projects", json={"name": name, "author": "alice", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _design(client, pid, name="Baseline", config=CONFIG, **extra):
    r = client.post(f"{API}/projects/{pid}/designs", json={"name": name, "config": config, "author": "alice", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_info(client, backend):
    info = client.get(f"{API}/info").json()
    assert info["storage"] == ("files" if backend == "files" else "database")
    assert info["writable"] is True
    assert info["location"]
    assert info["examples_available"] is True


def test_project_crud(client):
    assert client.get(f"{API}/projects").json() == []
    p = _project(client, description="first")
    assert p["id"] == "test-engine"
    assert p["created_by"] == "alice"
    assert p["design_count"] == 0
    assert p["created_at"].endswith("Z")

    r = client.patch(f"{API}/projects/{p['id']}", json={"name": "Renamed", "description": "d2"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed" and r.json()["id"] == "test-engine"

    other = _project(client, name="Other")
    client.patch(f"{API}/projects/{p['id']}", json={"description": "touch"})
    assert [x["id"] for x in client.get(f"{API}/projects").json()] == [p["id"], other["id"]]

    detail = client.get(f"{API}/projects/{p['id']}").json()
    assert detail["project"]["description"] == "touch" and detail["designs"] == []

    assert client.delete(f"{API}/projects/{p['id']}").json() == {"ok": True}
    assert client.get(f"{API}/projects/{p['id']}").status_code == 404
    assert client.delete(f"{API}/projects/{p['id']}").status_code == 404
    assert [x["id"] for x in client.get(f"{API}/projects").json()] == [other["id"]]


def test_ids_slugs_and_validation(client):
    assert _project(client, name="My Engine!")["id"] == "my-engine"
    assert _project(client, name="my engine")["id"] == "my-engine-2"
    assert _project(client, name="My  Engine")["id"] == "my-engine-3"
    long_id = _project(client, name="x" * 120)["id"]
    assert len(long_id) == 48
    assert len(_project(client, name="x" * 120)["id"]) == 48
    assert _project(client, name="Überdruck Triebwerk")["id"] == "uberdruck-triebwerk"

    assert client.post(f"{API}/projects", json={"name": ""}).status_code == 422
    assert client.post(f"{API}/projects", json={"name": "   "}).status_code == 422
    assert client.post(f"{API}/projects", json={"name": "x" * 121}).status_code == 422
    for bad in ("Bad_ID", ".hidden", "-x", "%2E%2E", "a" * 65):
        assert client.get(f"{API}/projects/{bad}").status_code in (404, 422), bad
    assert client.get(f"{API}/projects/Bad_ID").status_code == 422
    assert client.get(f"{API}/projects/my-engine/designs/..%2F..%2Fx").status_code in (404, 422)
    assert client.get(f"{API}/projects/nope").status_code == 404

    pid = "my-engine"
    assert _design(client, pid, name="Design A")["id"] == "design-a"
    assert _design(client, pid, name="Design A")["id"] == "design-a-2"


def test_file_store_rejects_traversal(tmp_path):
    store = FileStore(tmp_path / "ws")
    for bad in ("../etc", "..", "a/b", "", "UP"):
        with pytest.raises(Invalid):
            store.get_project(bad)
    store.create_project("P")
    with pytest.raises(Invalid):
        store.get_design("p", "../../project")


def test_design_lifecycle(client):
    pid = _project(client)["id"]
    d = _design(client, pid, description="first cut")
    did = d["id"]
    assert d["config"] == CONFIG
    assert d["revision"] == 1 and d["head_version"] is None
    assert d["has_unsaved_changes"] is True
    assert d["status"] == "concept" and d["is_baseline"] is False
    assert d["kpis"] == {} and d["derived_from"] is None
    assert d["updated_by"] == "alice"

    base = f"{API}/projects/{pid}/designs/{did}"
    kpis = {"thrust_N": 2000.0, "isp_s": 231.5}
    r = client.post(f"{base}/versions", json={"message": "initial", "author": "bob", "kpis": kpis})
    assert r.status_code == 201, r.text
    assert r.json()["number"] == 1 and r.json()["author"] == "bob" and r.json()["kpis"] == kpis
    d = client.get(base).json()
    assert d["head_version"] == 1 and d["has_unsaved_changes"] is False and d["kpis"] == kpis

    cfg2 = {**CONFIG, "chamber": {**CONFIG["chamber"], "contraction_ratio": 5.0}}
    r = client.put(f"{base}/draft", json={"config": cfg2, "revision": 1, "author": "bob"})
    assert r.status_code == 200
    assert r.json()["revision"] == 2 and r.json()["has_unsaved_changes"] is True
    assert r.json()["updated_at"].endswith("Z")

    r = client.put(f"{base}/draft", json={"config": CONFIG, "revision": 1})
    assert r.status_code == 409
    assert r.json()["detail"]["current_revision"] == 2
    assert "message" in r.json()["detail"]
    assert client.get(base).json()["config"] == cfg2

    # Draft identical to head → clean again.
    r = client.put(f"{base}/draft", json={"config": CONFIG, "revision": 2})
    assert r.json() == {**r.json(), "revision": 3, "has_unsaved_changes": False}
    client.put(f"{base}/draft", json={"config": cfg2, "revision": 3})

    assert client.post(f"{base}/versions", json={"message": "CR 5"}).json()["number"] == 2
    assert client.post(f"{base}/versions", json={"message": ""}).status_code == 422
    assert client.post(f"{base}/versions", json={}).status_code == 422
    assert client.post(f"{base}/versions", json={"message": "x" * 501}).status_code == 422

    versions = client.get(f"{base}/versions").json()
    assert [v["number"] for v in versions] == [2, 1]
    assert versions[0]["author"] == "anonymous" and versions[1]["kpis"] == kpis
    assert "config" not in versions[0]
    v1 = client.get(f"{base}/versions/1").json()
    assert v1["config"] == CONFIG and v1["message"] == "initial"
    assert client.get(f"{base}/versions/9").status_code == 404

    r = client.post(f"{base}/versions/1/restore", json={"author": "carol"})
    assert r.status_code == 200
    d = r.json()
    assert d["config"] == CONFIG and d["revision"] == 5 and d["updated_by"] == "carol"
    assert d["head_version"] == 2 and d["has_unsaved_changes"] is True
    assert len(client.get(f"{base}/versions").json()) == 2
    d = client.post(f"{base}/versions/2/restore").json()
    assert d["config"] == cfg2 and d["has_unsaved_changes"] is False and d["revision"] == 6

    r = client.patch(base, json={"name": "Renamed", "status": "preliminary", "description": "x"})
    assert r.status_code == 200
    assert r.json()["status"] == "preliminary" and r.json()["name"] == "Renamed" and "config" not in r.json()
    assert r.json()["revision"] == 6
    assert client.patch(base, json={"status": "bogus"}).status_code == 422

    summary = client.get(f"{API}/projects/{pid}").json()
    assert summary["project"]["design_count"] == 1
    assert summary["designs"][0]["id"] == did and "config" not in summary["designs"][0]

    assert client.delete(base).json() == {"ok": True}
    assert client.get(base).status_code == 404
    assert client.get(f"{base}/versions").status_code == 404
    assert client.get(f"{API}/projects/{pid}").json()["designs"] == []


def test_config_validation_and_size(client):
    pid = _project(client)["id"]
    r = client.post(f"{API}/projects/{pid}/designs", json={"name": "No config"})
    assert r.status_code == 422
    big = {"engine": "X", "blob": "x" * (2 * 1024 * 1024 + 10)}
    r = client.post(f"{API}/projects/{pid}/designs", json={"name": "Big", "config": big})
    assert r.status_code == 413
    did = _design(client, pid)["id"]
    r = client.put(f"{API}/projects/{pid}/designs/{did}/draft", json={"config": big, "revision": 1})
    assert r.status_code == 413
    # Invalid engine configs are fine as drafts.
    r = client.put(f"{API}/projects/{pid}/designs/{did}/draft", json={"config": {"half": "done"}, "revision": 1})
    assert r.status_code == 200


def test_baseline_exclusive(client):
    pid = _project(client)["id"]
    a, b = _design(client, pid, name="A")["id"], _design(client, pid, name="B")["id"]
    client.patch(f"{API}/projects/{pid}/designs/{a}", json={"is_baseline": True})
    flags = {d["id"]: d["is_baseline"] for d in client.get(f"{API}/projects/{pid}").json()["designs"]}
    assert flags == {a: True, b: False}
    client.patch(f"{API}/projects/{pid}/designs/{b}", json={"is_baseline": True})
    designs = client.get(f"{API}/projects/{pid}").json()["designs"]
    assert {d["id"]: d["is_baseline"] for d in designs} == {a: False, b: True}
    assert designs[0]["id"] == b  # baseline listed first
    client.patch(f"{API}/projects/{pid}/designs/{b}", json={"is_baseline": False})
    assert not any(d["is_baseline"] for d in client.get(f"{API}/projects/{pid}").json()["designs"])


def test_derived_from(client):
    pid = _project(client)["id"]
    src = _design(client, pid, name="Source")["id"]
    base = f"{API}/projects/{pid}/designs/{src}"
    client.post(f"{base}/versions", json={"message": "v1"})
    cfg2 = {**CONFIG, "engine": "TEST-2"}
    client.put(f"{base}/draft", json={"config": cfg2, "revision": 1})

    r = client.post(f"{API}/projects/{pid}/designs", json={"name": "Branch WC", "derived_from": {"design_id": src}})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["config"] == cfg2
    assert d["derived_from"] == {"design_id": src, "design_name": "Source", "version": None}
    assert d["head_version"] is None and d["revision"] == 1

    d = client.post(f"{API}/projects/{pid}/designs", json={
        "name": "Branch V1", "config": None, "derived_from": {"design_id": src, "version": 1},
    }).json()
    assert d["config"] == CONFIG
    assert d["derived_from"] == {"design_id": src, "design_name": "Source", "version": 1}

    own = {"engine": "OWN"}
    d = client.post(f"{API}/projects/{pid}/designs", json={
        "name": "Branch own", "config": own, "derived_from": {"design_id": src},
    }).json()
    assert d["config"] == own and d["derived_from"]["design_id"] == src

    r = client.post(f"{API}/projects/{pid}/designs", json={"name": "X", "derived_from": {"design_id": "nope"}})
    assert r.status_code == 404
    r = client.post(f"{API}/projects/{pid}/designs", json={"name": "X", "derived_from": {"design_id": src, "version": 7}})
    assert r.status_code == 404


def test_export_import_roundtrip(client):
    pid = _project(client, name="Roundtrip", description="rt")["id"]
    a = _design(client, pid, name="Alpha")["id"]
    client.post(f"{API}/projects/{pid}/designs/{a}/versions", json={"message": "a1", "kpis": {"k": 1}, "author": "bob"})
    client.put(f"{API}/projects/{pid}/designs/{a}/draft", json={"config": {**CONFIG, "engine": "A2"}, "revision": 1})
    client.post(f"{API}/projects/{pid}/designs/{a}/versions", json={"message": "a2"})
    client.patch(f"{API}/projects/{pid}/designs/{a}", json={"is_baseline": True, "status": "detailed"})
    client.post(f"{API}/projects/{pid}/designs", json={"name": "Beta", "derived_from": {"design_id": a, "version": 1}})

    bundle = client.get(f"{API}/projects/{pid}/export").json()
    assert bundle["format"] == "resa-project" and bundle["format_version"] == 1
    assert bundle["project"]["name"] == "Roundtrip" and bundle["project"]["created_by"] == "alice"
    alpha = next(d for d in bundle["designs"] if d["id"] == a)
    assert [v["number"] for v in alpha["versions"]] == [1, 2]
    assert alpha["versions"][0]["config"] == CONFIG

    r = client.post(f"{API}/import", json={"bundle": bundle, "author": "dave"})
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["id"] == "roundtrip-2" and new["name"] == "Roundtrip" and new["design_count"] == 2
    assert new["created_by"] == "dave"

    again = client.get(f"{API}/projects/{new['id']}/export").json()
    for d_old, d_new in zip(bundle["designs"], again["designs"]):
        for key in ("id", "name", "description", "status", "is_baseline", "derived_from", "config", "versions"):
            assert d_old[key] == d_new[key], key
    imported = client.get(f"{API}/projects/{new['id']}/designs/{a}").json()
    assert imported["head_version"] == 2 and imported["kpis"] == {} and imported["has_unsaved_changes"] is False
    assert client.get(f"{API}/projects/{new['id']}/designs/{a}/versions/1").json()["kpis"] == {"k": 1}

    for bad in ({}, {**bundle, "format": "x"}, {**bundle, "format_version": 2}, {**bundle, "designs": "x"},
                {**bundle, "designs": [{"name": "n", "config": "notadict"}]}):
        assert client.post(f"{API}/import", json={"bundle": bad}).status_code == 422
    assert len(client.get(f"{API}/projects").json()) == 2


def test_examples_import(client, backend):
    from resa.config.schema import EngineConfig

    r = client.post(f"{API}/examples", json={"author": "seed"})
    assert r.status_code == 200, r.text
    projects = r.json()
    assert len(projects) >= 1
    names = {p["name"] for p in projects}
    assert "EX15" in names
    for p in projects:
        detail = client.get(f"{API}/projects/{p['id']}").json()
        assert detail["designs"], p["name"]
        assert sum(d["is_baseline"] for d in detail["designs"]) <= 1
        for summary in detail["designs"]:
            d = client.get(f"{API}/projects/{p['id']}/designs/{summary['id']}").json()
            assert d["head_version"] == 1 and d["has_unsaved_changes"] is False
            assert "base" not in d["config"]
            EngineConfig.model_validate(d["config"])
            v = client.get(f"{API}/projects/{p['id']}/designs/{d['id']}/versions").json()
            assert v[0]["message"].startswith("Imported from configs/projects/")
    ex15 = next(p for p in projects if p["name"] == "EX15")
    ex15_designs = client.get(f"{API}/projects/{ex15['id']}").json()["designs"]
    assert ex15_designs[0]["name"] == "design" and ex15_designs[0]["is_baseline"]
    assert "regen" not in {d["name"] for d in ex15_designs}  # fragment, not an engine config
    if backend == "files":
        from resa.config.loader import load_config
        from resa_studio.workspace import get_store

        store = get_store()
        path = store.root / ex15["id"] / "designs" / f"{ex15_designs[0]['id']}.yaml"
        assert load_config(path).engine  # the working copy is directly runnable
    # Idempotent by project name.
    assert client.post(f"{API}/examples").json() == []


def test_concurrent_versions_get_unique_numbers(client):
    from concurrent.futures import ThreadPoolExecutor

    from resa_studio.workspace import get_store

    store = get_store()
    pid = store.create_project("Concurrent")["id"]
    did = store.create_design(pid, "D", config=CONFIG)["id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(lambda i: store.create_version(pid, did, f"m{i}")["number"], range(16)))
    assert sorted(numbers) == list(range(1, 17))
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda i: store.create_design(pid, "Same", config=CONFIG)["id"], range(8)))
    assert len(set(ids)) == 8


def test_file_layout(tmp_path, monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "ws"
    monkeypatch.setenv("RESA_WORKSPACE_DIR", str(root))
    reset_store_cache()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    try:
        pid = _project(client, name="Layout")["id"]
        did = _design(client, pid, name="Main")["id"]
        client.post(f"{API}/projects/{pid}/designs/{did}/versions", json={"message": "m", "kpis": {"a": 1}})

        pdir = root / pid
        assert yaml.safe_load((pdir / "project.yaml").read_text())["name"] == "Layout"
        assert yaml.safe_load((pdir / "designs" / f"{did}.yaml").read_text()) == CONFIG
        text = (pdir / "designs" / f"{did}.yaml").read_text()
        assert text.startswith("engine: TEST-1")  # insertion order kept
        meta = yaml.safe_load((pdir / "designs" / f"{did}.meta.yaml").read_text())
        assert meta["name"] == "Main" and meta["revision"] == 1 and isinstance(meta["updated_at"], str)
        v1 = yaml.safe_load((pdir / "history" / did / "v0001.yaml").read_text())
        assert v1["number"] == 1 and v1["config"] == CONFIG and v1["kpis"] == {"a": 1}
        assert not list(pdir.rglob("*.tmp"))

        # A design YAML dropped in by hand (e.g. via git) shows up with defaults.
        (pdir / "designs" / "manual.yaml").write_text(yaml.safe_dump(CONFIG))
        d = client.get(f"{API}/projects/{pid}/designs/manual").json()
        assert d["name"] == "manual" and d["revision"] == 1 and d["config"] == CONFIG

        client.delete(f"{API}/projects/{pid}/designs/{did}")
        assert not (pdir / "designs" / f"{did}.yaml").exists()
        assert not (pdir / "history" / did).exists()
        trashed = list((root / ".trash").iterdir())
        assert len(trashed) == 1 and (trashed[0] / f"{did}.yaml").is_file()
        assert (trashed[0] / "history" / "v0001.yaml").is_file()

        client.delete(f"{API}/projects/{pid}")
        assert not pdir.exists()
        assert any(p.name.endswith(f"-{pid}") and (p / "project.yaml").is_file() for p in (root / ".trash").iterdir())
        assert client.get(f"{API}/projects").json() == []
    finally:
        reset_store_cache()


def test_no_storage_on_vercel(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("VERCEL", "1")
    reset_store_cache()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    try:
        info = client.get(f"{API}/info").json()
        assert info["storage"] == "none" and info["writable"] is False
        for method, path in (("get", "/projects"), ("post", "/projects"), ("get", "/projects/x"),
                             ("post", "/examples"), ("post", "/import")):
            r = client.request(method.upper(), f"{API}{path}", json={"name": "x", "bundle": {}})
            assert r.status_code == 503, path
            assert "No server-side workspace storage configured" in r.json()["detail"]
    finally:
        reset_store_cache()


def test_default_location_is_repo_workspace(monkeypatch):
    from resa_studio.workspace.config import DEFAULT_WORKSPACE_DIR, get_store

    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    reset_store_cache()
    try:
        store = get_store()
        assert isinstance(store, FileStore)
        assert store.root == DEFAULT_WORKSPACE_DIR
        assert DEFAULT_WORKSPACE_DIR.parent == Path(__file__).resolve().parents[1]
        assert store.location == "workspace/ folder"
    finally:
        reset_store_cache()
