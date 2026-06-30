"""RESA engine config + regen integration smoke tests."""
from pathlib import Path

import pytest

from resa.config.loader import load_config
from resa.pipeline import run
from resa.reporting.report import write_report


def test_engine_config_accepts_regen_block():
    cfg = load_config("configs/projects/e2_c1/design_regen.yaml")
    assert cfg.regen is not None
    assert cfg.regen.contour.type == "from_engine"
    assert cfg.regen.solver.enabled is True


def test_regen_report_artifacts(tmp_path):
    pytest.importorskip("plotly")
    cfg_path = "configs/ci/e2_c1_design_regen.yaml"
    cfg = load_config(cfg_path)
    res = run(cfg)
    outdir, res = write_report(res, cfg, cfg_path, out_root=tmp_path)
    assert res.regen is not None
    assert (outdir / f"{res.regen.tag}_geometry.csv").exists()
    assert (outdir / f"{res.regen.tag}_results.csv").exists()
    assert (outdir / f"{res.regen.tag}_3d.html").exists()
    assert (outdir / f"{res.regen.tag}_geometry_plots.html").exists()
    assert (outdir / f"{res.regen.tag}_results_plots.html").exists()
