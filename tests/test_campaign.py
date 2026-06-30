"""Campaign runner smoke tests."""
from pathlib import Path

import pytest

from resa.campaign import load_campaign, run_campaign


def test_load_campaign_paths():
    spec = load_campaign("campaigns/ci_golden.yaml")
    assert spec.name == "ci_golden"
    assert len(spec.configs) == 2
    assert all(Path(c).exists() for c in spec.configs)


def test_run_ci_campaign(tmp_path):
    pytest.importorskip("plotly")
    out = run_campaign("campaigns/ci_golden.yaml", out_root=tmp_path, verbose=False)
    assert out == tmp_path
    assert (tmp_path / "campaign_rollup.csv").exists()
    subdirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(subdirs) == 2
