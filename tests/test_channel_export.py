"""Channel selection for regen mesh / CSV / 3D exports."""
import pytest

from resa.regen_channels.config import ExportCfg, RegenConfig
from resa.regen_channels.contour import build_contour
from resa.regen_channels.layout import ChannelLayout
from resa.regen_channels.mesh import (
    centerlines_export_basename,
    html_3d_export_basename,
    mesh_export_basename,
    resolve_channel_ids,
)

BASE = dict(
    meta={"name": "channel_export"},
    contour={"type": "parametric", "parametric": dict(
        chamber_radius=40e-3, chamber_length=70e-3, throat_radius=14.8e-3,
        expansion_ratio=4.0, nozzle_type="bell")},
    channels={"count": 8, "inner_wall_thickness": 0.8e-3, "height": 2e-3,
              "rib": {"mode": "fixed_width", "width": 1e-3},
              "helix": {"profile": 0.0}},
    geometry={"n_stations": 20},
    solver={"enabled": False},
)


@pytest.fixture
def layout():
    cfg = RegenConfig.model_validate(BASE)
    return ChannelLayout(build_contour(cfg.contour), cfg)


def test_resolve_channel_ids_scalar_int(layout):
    assert resolve_channel_ids(layout, 3) == [3]


def test_resolve_channel_ids_rejects_out_of_range(layout):
    with pytest.raises(ValueError, match="out of range"):
        resolve_channel_ids(layout, 99)


def test_export_channel_overrides_per_format(layout):
    export = ExportCfg(channel=2, stl_channels=[0, 1], step_channels="all")
    assert export.channel_ids(layout, "stl_channels") == [2]
    assert export.channel_ids(layout, "step_channels") == [2]


def test_export_basenames_single_channel():
    assert mesh_export_basename("e2", [0], "step") == "e2_channel_00_mm.step"
    assert mesh_export_basename("e2", [0, 1], "stl") == "e2_channels_mm.stl"
    assert centerlines_export_basename("e2", [5]) == "e2_channel_05_centerline_mm.csv"
    assert html_3d_export_basename("e2", [5]) == "e2_channel_05_3d.html"
