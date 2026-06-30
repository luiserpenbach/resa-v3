"""STEP export smoke test."""
import pytest

from resa.regen_channels.config import RegenConfig
from resa.regen_channels.contour import build_contour
from resa.regen_channels.layout import ChannelLayout
from resa.regen_channels.mesh import write_step

BASE = dict(
    meta={"name": "step_test"},
    contour={"type": "parametric", "parametric": dict(
        chamber_radius=40e-3, chamber_length=70e-3, throat_radius=14.8e-3,
        expansion_ratio=4.0, nozzle_type="bell")},
    channels={"count": 4, "inner_wall_thickness": 0.8e-3, "height": 2e-3,
              "rib": {"mode": "fixed_width", "width": 1e-3},
              "helix": {"profile": 0.0}},
    geometry={"n_stations": 40},
    solver={"enabled": False},
)


def test_write_step(tmp_path):
    pytest.importorskip("OCP")
    cfg = RegenConfig.model_validate(BASE)
    lay = ChannelLayout(build_contour(cfg.contour), cfg)
    out = tmp_path / "channels.step"
    write_step(str(out), lay, channel_ids=[0, 1])
    assert out.exists()
    assert out.stat().st_size > 1000
    text = out.read_text(encoding="utf-8", errors="ignore")
    assert "ISO-10303" in text or "FILE" in text


def test_write_step_avoids_assembly_tree(tmp_path):
    """NX rejects STEP files with huge nested assembly graphs."""
    pytest.importorskip("OCP")
    cfg = RegenConfig.model_validate(BASE)
    lay = ChannelLayout(build_contour(cfg.contour), cfg)
    out = tmp_path / "channel_00.step"
    write_step(str(out), lay, channel_ids=[0])
    text = out.read_text(encoding="utf-8", errors="ignore")
    assert text.count("NEXT_ASSEMBLY_USAGE_OCCURRENCE") == 0


def test_write_step_smooth_surfaces(tmp_path):
    """Default STEP export uses six B-spline faces per channel, not STL facets."""
    pytest.importorskip("OCP")
    cfg = RegenConfig.model_validate(BASE)
    lay = ChannelLayout(build_contour(cfg.contour), cfg)
    out = tmp_path / "channels_smooth.step"
    write_step(str(out), lay, channel_ids=[0, 1])
    text = out.read_text(encoding="utf-8", errors="ignore")
    assert text.count("ADVANCED_FACE") == 12
    assert text.count("B_SPLINE_SURFACE") >= 8


def test_write_step_faceted_fallback(tmp_path):
    pytest.importorskip("OCP")
    cfg = RegenConfig.model_validate(BASE)
    lay = ChannelLayout(build_contour(cfg.contour), cfg)
    out = tmp_path / "channels_faceted.step"
    write_step(str(out), lay, channel_ids=[0], faceted=True)
    text = out.read_text(encoding="utf-8", errors="ignore")
    assert text.count("ADVANCED_FACE") > 12
