"""PDF report generation smoke test."""
import numpy as np
import pytest

from resa.config.loader import load_config
from resa.pipeline import run
from resa.reporting.report import write_report


@pytest.fixture(scope="module")
def _pdf_deps():
    pytest.importorskip("matplotlib")
    pytest.importorskip("reportlab")


def test_pdf_report_generated(tmp_path, _pdf_deps):
    # CI table-backend config: runs offline (no rocketcea / Fortran needed).
    cfg = load_config("configs/ci/e2_c1_design_regen.yaml")
    res = run(cfg)
    outdir, res = write_report(
        res, cfg, "configs/ci/e2_c1_design_regen.yaml", out_root=tmp_path)
    pdf = outdir / "report.pdf"
    assert pdf.exists()
    assert pdf.stat().st_size > 5000
    assert res.regen is not None


def test_envelope_heatmap_orientation(_pdf_deps, monkeypatch):
    """imshow must receive isp_s as (n_of, n_t) — rows = O/F = y axis."""
    import matplotlib.axes

    from resa.reporting.pdf_plots import envelope_figure
    from resa.results import EnvelopeResult

    n_of, n_t = 4, 7   # deliberately non-square: a transpose cannot hide
    env = EnvelopeResult(
        throttle_frac=np.linspace(0.4, 1.1, n_t),
        of=np.linspace(2.0, 5.0, n_of),
        pc_bar=np.full((n_of, n_t), 20.0),
        thrust_N=np.full((n_of, n_t), 1e4),
        isp_s=np.tile(np.linspace(200.0, 250.0, n_t), (n_of, 1)),
        separated=np.zeros((n_of, n_t), dtype=bool),
    )

    captured = {}
    orig = matplotlib.axes.Axes.imshow

    def spy(self, X, **kwargs):
        captured["shape"] = np.asarray(X).shape
        return orig(self, X, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "imshow", spy)
    assert envelope_figure(env)
    assert captured["shape"] == (n_of, n_t)
