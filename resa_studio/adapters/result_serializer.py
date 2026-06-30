"""EngineResult → JSON-safe dicts for API responses."""
from __future__ import annotations

from typing import Any

import numpy as np

from resa.results import EngineResult, offdesign_to_dict


def _clean(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (np.floating, np.integer)):
        return float(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def result_to_dict(res: EngineResult, *, include_arrays: bool = False) -> dict[str, Any]:
    """Serialize EngineResult. Set include_arrays for contour/sweep point data."""
    from dataclasses import asdict

    def scalars(obj) -> dict[str, Any]:
        return {
            k: _clean(v)
            for k, v in asdict(obj).items()
            if not isinstance(v, np.ndarray)
        }

    payload: dict[str, Any] = {
        "engine": res.engine,
        "config_hash": res.config_hash,
        "mode": res.mode,
        "summary": res.summary(),
        "warnings": list(res.warnings),
        "combustion": scalars(res.combustion),
        "thrust_chamber": scalars(res.thrust_chamber),
        "provenance": dict(res.thrust_chamber.provenance),
    }

    if res.contour is not None:
        cont = scalars(res.contour)
        cont["total_length_m"] = float(res.contour.total_length_m)
        if include_arrays:
            cont["stations"] = {
                "x_m": _clean(res.contour.x_m),
                "r_m": _clean(res.contour.r_m),
                "area_m2": _clean(res.contour.area_m2),
                "mach": _clean(res.contour.mach),
            }
        payload["contour"] = cont

    if res.offdesign is not None:
        payload["offdesign"] = offdesign_to_dict(res.offdesign)

    if res.uncertainty is not None:
        u = res.uncertainty
        payload["uncertainty"] = {
            "eta_cstar_tol": u.eta_tol,
            "low": scalars(u.tc_lo),
            "high": scalars(u.tc_hi),
        }

    if res.regen is not None:
        payload["regen"] = res.regen.summary()

    return payload
