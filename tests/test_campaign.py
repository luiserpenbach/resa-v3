"""Campaign runner smoke tests."""
from pathlib import Path

import pytest

from resa.campaign import load_campaign, run_campaign


def test_load_campaign_paths():
    spec = load_campaign("campaigns/ci_golden.yaml")
    assert spec.name == "ci_golden"
    assert len(spec.configs) == 2
    assert all(Path(c).exists() for c in spec.configs)


def _write_sweep_campaign(tmp_path, body: str) -> Path:
    path = tmp_path / "sweep.yaml"
    repo = Path(".").resolve()
    path.write_text(body.format(repo=repo.as_posix()), encoding="utf-8")
    return path


def test_sweep_1d_with_failure_tolerance(tmp_path):
    import csv

    camp = _write_sweep_campaign(tmp_path, """
name: pc_study
output: {repo}/ignored
base: {repo}/configs/ci/e2_c1_design.yaml
sweep:
  operating_point.pc_bar: [20, 25, 30]
  chamber.contraction_ratio:
    values: [12.0, 2.0]      # 2.0 is geometrically infeasible -> error rows
""")
    out = run_campaign(camp, out_root=tmp_path / "out", verbose=False)
    rows = list(csv.DictReader((out / "sweep_rollup.csv").open()))
    assert len(rows) == 6
    ok = [r for r in rows if not r.get("error")]
    bad = [r for r in rows if r.get("error")]
    assert len(ok) == 3 and len(bad) == 3
    assert {float(r["operating_point.pc_bar"]) for r in ok} == {20.0, 25.0, 30.0}
    # isp responds to pc
    isps = {float(r["operating_point.pc_bar"]): float(r["isp_s"]) for r in ok}
    assert isps[30.0] != isps[20.0]
    assert all("infeasible" in r["error"] for r in bad)


def test_sweep_range_axis_and_plots(tmp_path):
    pytest.importorskip("plotly")
    import csv

    camp = _write_sweep_campaign(tmp_path, """
name: eps_study
output: {repo}/ignored
base: {repo}/configs/ci/e2_c1_design.yaml
sweep:
  operating_point.eta_cstar:
    range: [0.85, 0.95]
    n: 3
""")
    out = run_campaign(camp, out_root=tmp_path / "out", verbose=False)
    rows = list(csv.DictReader((out / "sweep_rollup.csv").open()))
    assert len(rows) == 3
    assert (out / "sweep_plots.html").exists()


def test_sweep_regen_kpis(tmp_path):
    pytest.importorskip("CoolProp")
    import csv

    camp = _write_sweep_campaign(tmp_path, """
name: regen_study
output: {repo}/ignored
base: {repo}/configs/ci/e2_c1_design_regen.yaml
sweep_regen: true
sweep:
  regen.channels.height: [0.0005, 0.001]
""")
    out = run_campaign(camp, out_root=tmp_path / "out", verbose=False)
    rows = list(csv.DictReader((out / "sweep_rollup.csv").open()))
    assert len(rows) == 2
    t_walls = [float(r["T_wall_max_K"]) for r in rows]
    assert all(t > 300 for t in t_walls)
    assert t_walls[0] != t_walls[1]     # channel height moves the wall temp


def test_sweep_requires_base():
    import yaml as _yaml
    from resa.campaign import load_campaign

    from pathlib import Path as _P
    import tempfile
    with tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, dir="."
    ) as f:
        _yaml.safe_dump({"name": "x", "sweep": {"a.b": [1, 2]}}, f)
        p = f.name
    try:
        with pytest.raises(ValueError, match="requires a 'base'"):
            load_campaign(p)
    finally:
        _P(p).unlink()


def test_run_ci_campaign(tmp_path):
    pytest.importorskip("plotly")
    out = run_campaign("campaigns/ci_golden.yaml", out_root=tmp_path, verbose=False)
    assert out == tmp_path
    assert (tmp_path / "campaign_rollup.csv").exists()
    subdirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(subdirs) == 2
