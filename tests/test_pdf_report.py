"""PDF report generation smoke test."""
import pytest

from resa.config.loader import load_config
from resa.pipeline import run
from resa.reporting.report import write_report


@pytest.fixture(scope="module")
def _pdf_deps():
    pytest.importorskip("matplotlib")
    pytest.importorskip("reportlab")


def test_pdf_report_generated(tmp_path, _pdf_deps):
    cfg = load_config("configs/projects/e2_c1/design_regen.yaml")
    res = run(cfg)
    outdir, res = write_report(
        res, cfg, "configs/projects/e2_c1/design_regen.yaml", out_root=tmp_path)
    pdf = outdir / "report.pdf"
    assert pdf.exists()
    assert pdf.stat().st_size > 5000
    assert res.regen is not None
