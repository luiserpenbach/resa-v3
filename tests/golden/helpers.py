"""Shared helpers for golden regression tests (offline table combustion)."""
from __future__ import annotations

from pathlib import Path

import yaml

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

CI_E2_DESIGN = "configs/ci/e2_c1_design.yaml"
CI_E2_ASBUILT = "configs/ci/e2_c1_asbuilt.yaml"
CI_E2_HF02 = "configs/ci/e2_c1_hf02.yaml"
CI_EX15_DESIGN = "configs/ci/ex15_design.yaml"


def load_expected(name: str) -> dict:
    path = FIXTURES / name / "expected.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
