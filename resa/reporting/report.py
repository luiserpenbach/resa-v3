"""Report writer: one EngineResult -> one self-contained, traceable folder.

    out/<engine>_<config_hash>/
    ├── report.md            human summary + warnings + exact config used
    ├── report.pdf           printable full analysis (inputs, results, plots)
    ├── results.yaml         all scalar results + provenance (machine-readable)
    ├── summary.csv          one flat row (append across runs -> rollup)
    ├── contour.{html,csv}   geometry artifacts
    ├── mach.html            quasi-1D Mach distribution
    ├── offdesign_*.{html,csv}  throttle / OF-sweep / envelope (if configured)
    └── config_resolved.yaml composed + validated config snapshot

Every value in report.md's key table carries its SOURCE: input | calculated |
optimized — so an assumption can never masquerade as a result.
"""
from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

import numpy as np
import yaml

from ..config.schema import EngineConfig
from ..regen.integration import run_regen_for_engine
from ..results import EngineResult, offdesign_to_dict


def _clean(v):
    if isinstance(v, np.ndarray):
        return None
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, (np.floating, np.integer)):
        return float(v)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def _scalars(obj) -> dict:
    return {k: _clean(v) for k, v in asdict(obj).items()
            if not isinstance(v, np.ndarray)}


def _results_dict(res: EngineResult) -> dict:
    d = {
        "engine": res.engine,
        "config_hash": res.config_hash,
        "mode": res.mode,
        "warnings": list(res.warnings),
        "combustion": _scalars(res.combustion),
        "thrust_chamber": _scalars(res.thrust_chamber),
    }
    if res.contour is not None:
        cont = _scalars(res.contour)
        cont["total_length_m"] = float(res.contour.total_length_m)
        d["contour"] = cont
    if res.uncertainty is not None:
        u = res.uncertainty
        d["uncertainty"] = {
            "eta_cstar_tol": u.eta_tol,
            "low": _scalars(u.tc_lo),
            "high": _scalars(u.tc_hi),
        }
    if res.offdesign is not None:
        d["offdesign"] = offdesign_to_dict(res.offdesign)
    if res.regen is not None:
        d["regen"] = res.regen.summary()
    return d


def _row(L, name, value, source):
    L.append(f"| {name} | {value} | {source} |")


def _write_report_md(res: EngineResult, cfg: EngineConfig, cfg_yaml: str,
                     path: Path) -> None:
    tc, c = res.thrust_chamber, res.contour
    p = tc.provenance
    L = []
    L.append(f"# {res.engine} — {res.mode} report\n")
    L.append(f"`config_hash: {res.config_hash}` · mode: `{res.mode}` · "
             f"c* source: `{res.combustion.source}`\n")

    if res.warnings:
        L.append("## ⚠ Warnings\n")
        for w in res.warnings:
            L.append(f"- {w}")
        L.append("")

    L.append("## Key results\n")
    L.append("| quantity | value | source |")
    L.append("|---|---|---|")
    _row(L, "Thrust", f"{tc.thrust_N:.1f} N", p["thrust"])
    _row(L, "Chamber pressure", f"{tc.pc_bar:.2f} bar", p["pc"])
    _row(L, "O/F", f"{tc.of_ratio:.3f}", p["of_ratio"])
    _row(L, "Area ratio ε", f"{tc.eps:.3f}", p["eps"])
    _row(L, "Total mass flow", f"{tc.mdot_total_kg_s*1e3:.1f} g/s", p["mdot"])
    _row(L, "&nbsp;&nbsp;ox / fuel",
         f"{tc.mdot_ox_kg_s*1e3:.1f} / {tc.mdot_fuel_kg_s*1e3:.1f} g/s",
         p["mdot"])
    _row(L, "c* effective (η={:.2f})".format(tc.eta_cstar),
         f"{tc.cstar_eff_m_s:.1f} m/s", "calculated")
    cf_label = ("C_F" if tc.eta_cf == 1.0
                else f"C_F effective (η_CF={tc.eta_cf:.2f})")
    _row(L, cf_label, f"{tc.cf:.4f}", "calculated")
    _row(L, "Isp", f"{tc.isp_s:.2f} s", "calculated")
    _row(L, "Exit pressure", f"{tc.pe_bar:.3f} bar", "calculated")
    _row(L, "Exit Mach", f"{tc.exit_mach:.3f}", "calculated")
    _row(L, "Throat radius", f"{tc.throat_radius_m*1e3:.2f} mm", p["geometry"])
    _row(L, "Exit radius", f"{tc.exit_radius_m*1e3:.2f} mm", p["geometry"])
    if c is not None:
        _row(L, "Chamber radius", f"{c.chamber_radius_m*1e3:.2f} mm", "calculated")
        _row(L, "Chamber length (inj→throat)",
             f"{c.chamber_length_m*1e3:.1f} mm", "calculated")
        _row(L, "Divergent length", f"{c.divergent_length_m*1e3:.1f} mm",
             "calculated")
        _row(L, "Total length", f"{c.total_length_m*1e3:.1f} mm", "calculated")
        _row(L, "Contour method / θn / θe",
             f"{c.method} / {c.theta_n_deg:.1f}° / {c.theta_e_deg:.1f}°",
             "input" if cfg.chamber.theta_n_deg else "calculated")

    u = res.uncertainty
    if u is not None:
        L.append(f"\n## Uncertainty (η_c* = {tc.eta_cstar:.3f} ± {u.eta_tol:.3f})\n")
        L.append("| quantity | low (η−tol) | nominal | high (η+tol) |")
        L.append("|---|---|---|---|")
        rows = [
            ("Isp [s]", "isp_s", "{:.2f}"),
            ("Pc [bar]", "pc_bar", "{:.2f}"),
            ("Thrust [N]", "thrust_N", "{:.0f}"),
            ("Total ṁ [g/s]", "mdot_total_kg_s", None),
        ]
        for label, attr, fmt in rows:
            lo, nom, hi = (getattr(x, attr) for x in (u.tc_lo, tc, u.tc_hi))
            if abs(hi - lo) < 1e-12:
                continue                       # quantity unaffected in this mode
            if attr == "mdot_total_kg_s":
                lo, nom, hi = lo * 1e3, nom * 1e3, hi * 1e3
                fmt = "{:.1f}"
            L.append(f"| {label} | {fmt.format(lo)} | {fmt.format(nom)} | "
                     f"{fmt.format(hi)} |")

    od = res.offdesign
    if od is not None:
        L.append("\n## Off-design\n")
        if od.ox_throttle is not None:
            s = od.ox_throttle
            ok = ~s.separated
            n_sep = int(s.separated.sum())
            # full-flow CF is not valid past separation: quote attached range
            F, pc, of = (a[ok] if ok.any() else a
                         for a in (s.thrust_N, s.pc_bar, s.of))
            sep_note = (f" ({n_sep} pts separation risk, "
                        "excluded from ranges)" if n_sep else "")
            L.append(f"- **ox throttle** ({len(s.of)} pts): thrust "
                     f"{F.min():.0f}–{F.max():.0f} N, "
                     f"Pc {pc.min():.1f}–{pc.max():.1f} bar, "
                     f"O/F {of.min():.2f}–{of.max():.2f}{sep_note} → "
                     "`offdesign_ox_throttle.{html,csv}`")
        if od.of_sweep is not None:
            s = od.of_sweep
            i = int(s.isp_s.argmax())
            L.append(f"- **O/F sweep**: max Isp {s.isp_s[i]:.1f} s at "
                     f"O/F {s.of[i]:.2f} → `offdesign_of_sweep.{{html,csv}}`")
        if od.envelope is not None:
            L.append("- **envelope**: Isp heatmap + Pc contours → "
                     "`offdesign_envelope.html`")

    rg = res.regen
    if rg is not None:
        L.append("\n## Regen cooling\n")
        if rg.results is not None:
            s = rg.summary()
            L.append(f"- **Q_total**: {s['Q_total_kW']:.1f} kW")
            L.append(f"- **Δp**: {s['dp_bar']:.2f} bar")
            L.append(f"- **Outlet**: {s['outlet_T_K']:.1f} K / "
                     f"{s['outlet_p_bar']:.1f} bar")
            L.append(f"- **T_wall,max**: {s['T_wall_max_K']:.0f} K")
            if s.get("saturation_reached"):
                L.append("- ⚠ bulk coolant saturation reached")
        L.append(f"- Artifacts: `{rg.tag}_*.{{csv,html,stl,step}}`")

    L.append("\n## Config used\n")
    L.append("```yaml")
    L.append(cfg_yaml.rstrip())
    L.append("```")
    path.write_text("\n".join(L), encoding="utf-8")


def write_report(
    res: EngineResult, cfg: EngineConfig, cfg_path: str | Path,
    out_root: str | Path = "out",
) -> tuple[Path, EngineResult]:
    try:
        from . import plots
    except ImportError as e:
        raise RuntimeError(
            "writing reports needs plotly — pip install plotly"
        ) from e
    out_root = Path(out_root)
    outdir = out_root / f"{res.engine}_{res.config_hash}"
    outdir.mkdir(parents=True, exist_ok=True)

    if cfg.regen is not None and res.contour is not None:
        regen = run_regen_for_engine(
            cfg, res.thrust_chamber, res.combustion, res.contour, outdir)
        res = EngineResult(
            engine=res.engine, config_hash=res.config_hash, mode=res.mode,
            combustion=res.combustion, thrust_chamber=res.thrust_chamber,
            contour=res.contour, offdesign=res.offdesign,
            uncertainty=res.uncertainty, regen=regen,
            warnings=res.warnings + regen.warnings,
        )

    (outdir / "results.yaml").write_text(
        yaml.safe_dump(_results_dict(res), sort_keys=False,
                       default_flow_style=False),
        encoding="utf-8",
    )

    summary = res.summary()
    with (outdir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary))
        w.writeheader()
        w.writerow(summary)

    tc = res.thrust_chamber
    if res.contour is not None:
        np.savetxt(outdir / "contour.csv", res.contour.station_table(),
                   delimiter=",", header="x_m,r_m,area_m2,mach", comments="")
        plots.contour_figure(res.contour, title=f"{res.engine} contour"
                             ).write_html(outdir / "contour.html",
                                          include_plotlyjs="cdn")
        plots.mach_figure(res.contour).write_html(outdir / "mach.html",
                                                  include_plotlyjs="cdn")

    od = res.offdesign
    u = res.uncertainty
    if od is not None:
        for name, sweep, figfn in [
            ("ox_throttle", od.ox_throttle, plots.ox_throttle_figure),
            ("of_sweep", od.of_sweep, plots.of_sweep_figure),
        ]:
            if sweep is None:
                continue
            np.savetxt(outdir / f"offdesign_{name}.csv", sweep.table(),
                       delimiter=",", header=sweep.HEADER, comments="")
            band = None
            if u is not None and u.od_lo is not None:
                band = (getattr(u.od_lo, name), getattr(u.od_hi, name))
                if band[0] is None:
                    band = None
            figfn(sweep, nominal=tc, band=band).write_html(
                outdir / f"offdesign_{name}.html", include_plotlyjs="cdn")
        if od.envelope is not None:
            plots.envelope_figure(od.envelope, nominal=tc).write_html(
                outdir / "offdesign_envelope.html", include_plotlyjs="cdn")

    cfg_yaml = yaml.safe_dump(cfg.model_dump(), sort_keys=False)
    (outdir / "config_resolved.yaml").write_text(cfg_yaml, encoding="utf-8")
    _write_report_md(res, cfg, cfg_yaml, outdir / "report.md")

    try:
        from .pdf_report import write_pdf_report
        write_pdf_report(res, cfg, cfg_path, outdir, cfg_yaml=cfg_yaml)
    except ImportError:
        pass  # optional: pip install -e ".[plot,pdf]"

    return outdir, res
