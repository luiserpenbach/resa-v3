"""Config loader edge cases."""
from __future__ import annotations

from pathlib import Path

import pytest

from resa.config.loader import load_config, load_resolved_dict
from resa.config.schema import ChamberConfig, EngineConfig


def test_moc_contour_rejected_at_validation() -> None:
    with pytest.raises(ValueError, match="moc is not yet implemented"):
        ChamberConfig.model_validate({
            "contraction_ratio": 4.0,
            "l_star_m": 1.0,
            "contour": "moc",
        })


def test_empty_yaml_is_a_clear_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty or not a mapping"):
        load_config(empty)


def test_engine_name_rejects_path_traversal() -> None:
    data = load_resolved_dict("configs/ci/e2_c1_design.yaml")
    data["engine"] = "../tmp/evil"
    with pytest.raises(Exception, match="engine"):
        EngineConfig.model_validate(data)


def test_circular_base_inheritance_detected(tmp_path: Path) -> None:
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text("base: b.yaml\nengine: A\n", encoding="utf-8")
    b.write_text("base: a.yaml\nengine: B\n", encoding="utf-8")
    with pytest.raises(ValueError, match="circular base:"):
        load_config(a)
