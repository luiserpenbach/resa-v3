"""First-order propellant film cooling model.

Bookkeeping layer around the untouched single-point kernel:

- The film (``fraction`` of TOTAL propellant mass flow, taken from ``side``)
  does not combust, so the core burns at a shifted O/F.
- The film produces no thrust: delivered Isp = core Isp × (1 − fraction).
  This is the conservative bound; the (cold) film gas does expand in
  reality and would recover a little of it.
- Throat mass flux is taken from the core flow only (pc·At = ṁ_core·c*),
  slightly optimistic on chamber pressure for a given throat.
- Wall relief is applied in the regen solver as an adiabatic-wall
  temperature reduction: η(x) = exp(−(x − x_inj)/L) downstream of the
  injection station, T_aw_eff = η·T_film + (1−η)·T_aw. The decay length L
  is user-set (``effectiveness_length_m``) and NOT derived from
  ``fraction`` — coupling entrainment to the film budget is future work.

All limitations above are surfaced as run warnings.
"""
from __future__ import annotations

from ..config.schema import AnalyzePoint, FilmCoolingConfig, OperatingPoint
from ..results import FilmCoolingResult, ThrustChamberResult

_G0 = 9.80665

MODEL_NOTE = (
    "film cooling: first-order model — film produces no thrust "
    "(delivered Isp = core Isp x (1 - fraction)), throat sized from core "
    "flow only, effectiveness decay length is user-set (not derived from "
    "the film fraction)"
)


def core_of_ratio(of_overall: float, film: FilmCoolingConfig) -> float:
    """O/F of the combusting core when the film is diverted from one side."""
    f = film.fraction
    if film.side == "fuel":
        denom = 1.0 - f * (1.0 + of_overall)
        if denom <= 0:
            raise ValueError(
                f"film fraction {f:g} consumes the entire fuel flow at "
                f"O/F={of_overall:g}")
        return of_overall / denom
    of_core = of_overall - f * (1.0 + of_overall)
    if of_core <= 0:
        raise ValueError(
            f"film fraction {f:g} consumes the entire oxidizer flow at "
            f"O/F={of_overall:g}")
    return of_core


def core_operating_point(
    op: OperatingPoint, film: FilmCoolingConfig
) -> tuple[OperatingPoint, float]:
    """Design mode: thrust target unchanged, core burns at shifted O/F."""
    of_overall = op.of_ratio
    if of_overall is None:
        raise ValueError("film_cooling requires an explicit of_ratio")
    return op.model_copy(
        update={"of_ratio": core_of_ratio(of_overall, film)}), of_overall


def core_analyze_point(
    ap: AnalyzePoint, film: FilmCoolingConfig
) -> tuple[AnalyzePoint, float]:
    """Analyze mode: measured tank flows minus the film feed the core."""
    mdot_total = ap.mdot_ox_kg_s + ap.mdot_fuel_kg_s
    mdot_film = film.fraction * mdot_total
    if film.side == "fuel":
        core = ap.mdot_fuel_kg_s - mdot_film
        if core <= 0:
            raise ValueError(
                f"film flow {mdot_film:g} kg/s exceeds measured fuel flow "
                f"{ap.mdot_fuel_kg_s:g} kg/s")
        point = ap.model_copy(update={"mdot_fuel_kg_s": core})
    else:
        core = ap.mdot_ox_kg_s - mdot_film
        if core <= 0:
            raise ValueError(
                f"film flow {mdot_film:g} kg/s exceeds measured oxidizer flow "
                f"{ap.mdot_ox_kg_s:g} kg/s")
        point = ap.model_copy(update={"mdot_ox_kg_s": core})
    return point, ap.mdot_ox_kg_s / ap.mdot_fuel_kg_s


def build_result(
    tc_core: ThrustChamberResult,
    film: FilmCoolingConfig,
    of_overall: float,
    *,
    mdot_total_kg_s: float | None = None,
) -> FilmCoolingResult:
    """Delivered-performance bookkeeping around the core kernel result.

    ``mdot_total_kg_s``: pass the measured total in analyze mode; in design
    mode it derives from the sized core flow and the film fraction.
    """
    f = film.fraction
    if mdot_total_kg_s is None:
        mdot_total_kg_s = tc_core.mdot_total_kg_s / (1.0 - f)
    mdot_film = f * mdot_total_kg_s
    isp_delivered = tc_core.thrust_N / (mdot_total_kg_s * _G0)
    return FilmCoolingResult(
        fraction=float(f),
        side=film.side,
        of_overall=round(float(of_overall), 4),
        of_core=round(float(tc_core.of_ratio), 4),
        mdot_film_kg_s=round(float(mdot_film), 6),
        mdot_total_kg_s=round(float(mdot_total_kg_s), 6),
        isp_core_s=round(float(tc_core.isp_s), 2),
        isp_delivered_s=round(float(isp_delivered), 2),
    )
