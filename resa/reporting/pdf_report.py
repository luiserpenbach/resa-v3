"""PDF report generator — readable full analysis document with tables and plots."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterable

import yaml
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..config.schema import EngineConfig
from ..results import EngineResult
from . import pdf_plots


def _esc(text: object) -> str:
    """Escape text for reportlab Paragraph (XML)."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _para(text: object, style, *, br: bool = False) -> Paragraph:
    body = _esc(text)
    if br:
        body = body.replace("\n", "<br/>")
    return Paragraph(body, style)


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title2", parent=base["Title"], fontSize=20, spaceAfter=8,
            alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], fontSize=10, textColor=colors.grey,
            alignment=TA_CENTER, spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            "H1", parent=base["Heading1"], fontSize=14, spaceBefore=10,
            spaceAfter=6, textColor=colors.HexColor("#1e3a5f"),
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontSize=11, spaceBefore=8,
            spaceAfter=4, textColor=colors.HexColor("#334155"),
        ),
        "body": ParagraphStyle(
            "Body", parent=base["BodyText"], fontSize=9, leading=12,
        ),
        "small": ParagraphStyle(
            "Small", parent=base["BodyText"], fontSize=7.5, leading=9,
            textColor=colors.HexColor("#475569"),
        ),
        "warn": ParagraphStyle(
            "Warn", parent=base["BodyText"], fontSize=9, textColor=colors.HexColor("#b45309"),
        ),
    }


def _table(rows: list[list[str]], col_widths=None) -> Table:
    t = Table(rows, colWidths=col_widths, repeatRows=1 if len(rows) > 1 else 0)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _kv_table(pairs: Iterable[tuple[str, str]]) -> Table:
    rows = [["Parameter", "Value"]] + [[k, v] for k, v in pairs]
    return _table(rows, col_widths=[55 * mm, 115 * mm])


def _image_from_bytes(png: bytes, width=170 * mm) -> Image:
    img = Image(BytesIO(png))
    aspect = img.imageHeight / float(img.imageWidth)
    img.drawWidth = width
    img.drawHeight = width * aspect
    return img


def _plot_page(story, styles, title: str, png: bytes) -> None:
    story.append(Paragraph(title, styles["h1"]))
    story.append(Spacer(1, 2 * mm))
    story.append(_image_from_bytes(png))
    story.append(PageBreak())


def _summary_section(story, styles, res: EngineResult) -> None:
    tc, p = res.thrust_chamber, res.thrust_chamber.provenance
    story.append(Paragraph("Key results", styles["h1"]))
    rows = [
        ["Quantity", "Value", "Source"],
        ["Thrust", f"{tc.thrust_N:.1f} N", p["thrust"]],
        ["Chamber pressure", f"{tc.pc_bar:.2f} bar", p["pc"]],
        ["O/F", f"{tc.of_ratio:.3f}", p["of_ratio"]],
        ["Area ratio eps", f"{tc.eps:.3f}", p["eps"]],
        ["Total mass flow", f"{tc.mdot_total_kg_s * 1e3:.1f} g/s", p["mdot"]],
        ["Ox / fuel flow",
         f"{tc.mdot_ox_kg_s * 1e3:.1f} / {tc.mdot_fuel_kg_s * 1e3:.1f} g/s",
         p["mdot"]],
        [f"c* effective (eta={tc.eta_cstar:.2f})",
         f"{tc.cstar_eff_m_s:.1f} m/s", "calculated"],
        ["C_F", f"{tc.cf:.4f}", f"calculated ({tc.cf_source})"],
        ["eta_CF", f"{tc.eta_cf:.4f}", p.get("eta_cf", "input")],
        ["Isp", f"{tc.isp_s:.2f} s", "calculated"],
        ["Isp vacuum, ideal (no eta)",
         f"{tc.isp_vac_ideal_s:.2f} s" if tc.isp_vac_ideal_s else "-", tc.cf_source],
        ["Exit pressure", f"{tc.pe_bar:.3f} bar", "calculated"],
        ["Exit Mach", f"{tc.exit_mach:.3f}", "calculated"],
        ["Throat radius", f"{tc.throat_radius_m * 1e3:.2f} mm", p["geometry"]],
        ["Exit radius", f"{tc.exit_radius_m * 1e3:.2f} mm", p["geometry"]],
    ]
    if res.contour is not None:
        c = res.contour
        rows.extend([
            ["Chamber radius", f"{c.chamber_radius_m * 1e3:.2f} mm", "calculated"],
            ["Chamber length", f"{c.chamber_length_m * 1e3:.1f} mm", "calculated"],
            ["Divergent length", f"{c.divergent_length_m * 1e3:.1f} mm", "calculated"],
            ["Total length", f"{c.total_length_m * 1e3:.1f} mm", "calculated"],
        ])
    story.append(_table(rows, col_widths=[55 * mm, 55 * mm, 60 * mm]))
    story.append(Spacer(1, 6 * mm))


def _inputs_section(story, styles, cfg: EngineConfig) -> None:
    story.append(Paragraph("Analysis inputs", styles["h1"]))

    pr = cfg.propellants
    story.append(Paragraph("Propellants", styles["h2"]))
    story.append(_kv_table([
        ("Name", pr.name),
        ("Oxidizer (CoolProp)", pr.oxidizer),
        ("Fuel (CoolProp)", pr.fuel),
        ("Ox delivery temperature", f"{pr.ox_temp_K:.1f} K"),
        ("Fuel delivery temperature", f"{pr.fuel_temp_K:.1f} K"),
    ]))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Combustion model", styles["h2"]))
    comb_rows = [("Backend", cfg.combustion.backend)]
    if cfg.combustion.table and cfg.combustion.table.is_table:
        comb_rows.append(("O/F table range",
                          f"{cfg.combustion.table.of[0]:.2f} – "
                          f"{cfg.combustion.table.of[-1]:.2f} "
                          f"({len(cfg.combustion.table.of)} pts)"))
    story.append(_kv_table(comb_rows))
    story.append(Spacer(1, 4 * mm))

    if cfg.mode == "design" and cfg.operating_point is not None:
        op = cfg.operating_point
        story.append(Paragraph("Operating point (design targets)", styles["h2"]))
        story.append(_kv_table([
            ("Thrust target", f"{op.thrust_N:.0f} N"),
            ("Pc target", f"{op.pc_bar:.2f} bar"),
            ("O/F", f"{op.of_ratio:.3f}" if op.of_ratio else "optimize max Isp"),
            ("Area ratio eps",
             f"{op.eps:.3f}" if op.eps else
             (f"pe = {op.pe_bar:.2f} bar" if op.pe_bar else "optimize pe = p_amb")),
            ("eta_cstar", f"{op.eta_cstar:.3f}"),
            ("eta_cstar_tol", f"{op.eta_cstar_tol:.3f}" if op.eta_cstar_tol else "—"),
            ("eta_cf", f"{op.eta_cf:.3f}"),
            ("Ambient pressure", f"{op.p_amb_bar:.4f} bar"),
        ]))
    elif cfg.analyze_point is not None and cfg.geometry is not None:
        ap, g = cfg.analyze_point, cfg.geometry
        story.append(Paragraph("Measured geometry (analyze)", styles["h2"]))
        geo_rows = [("Throat diameter", f"{g.throat_diameter_m * 1e3:.3f} mm")]
        if g.eps is not None:
            geo_rows.append(("Area ratio eps", f"{g.eps:.4f}"))
        else:
            geo_rows.append(("Exit diameter", f"{g.exit_diameter_m * 1e3:.3f} mm"))
        story.append(_kv_table(geo_rows))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Analyze point (test flows)", styles["h2"]))
        story.append(_kv_table([
            ("Ox mass flow", f"{ap.mdot_ox_kg_s * 1e3:.2f} g/s"),
            ("Fuel mass flow", f"{ap.mdot_fuel_kg_s * 1e3:.2f} g/s"),
            ("eta_cstar", f"{ap.eta_cstar:.3f}"),
            ("eta_cstar_tol", f"{ap.eta_cstar_tol:.3f}" if ap.eta_cstar_tol else "—"),
            ("eta_cf", f"{ap.eta_cf:.3f}"),
            ("Ambient pressure", f"{ap.p_amb_bar:.4f} bar"),
        ]))

    ch = cfg.chamber
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Chamber / contour generation", styles["h2"]))
    story.append(_kv_table([
        ("Contraction ratio", f"{ch.contraction_ratio:.1f}"),
        ("L*", f"{ch.l_star_m:.3f} m"),
        ("Contour method", ch.contour),
        ("Bell fraction", f"{ch.bell_fraction:.2f}"),
        ("Convergent half-angle", f"{ch.conv_half_angle_deg:.1f} deg"),
        ("Bartz correction", f"{ch.bartz_correction:.3f}"),
        ("Stations", str(ch.n_stations)),
    ]))

    c = cfg.cooling
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Cooling block (throat fit check only" +
        (" - the regen block below drives the solver)" if cfg.regen is not None else ")"),
        styles["h2"]))
    story.append(_kv_table([
        ("Coolant", c.coolant),
        ("Channels", str(c.n_channels)),
        ("Channel w x h",
         f"{c.channel_width_m * 1e3:.2f} x {c.channel_height_m * 1e3:.2f} mm"),
        ("Rib width", f"{c.rib_width_m * 1e3:.2f} mm"),
        ("Wall thickness", f"{c.inner_wall_thickness_m * 1e3:.2f} mm"),
        ("Inlet T / p", f"{c.inlet_T_K:.1f} K / {c.inlet_p_bar:.1f} bar"),
    ]))
    if cfg.regen is not None:
        rs = cfg.regen.solver
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Regen block (solver input)", styles["h2"]))
        story.append(_kv_table([
            ("Coolant / side", f"{rs.coolant} / {rs.coolant_side or 'inferred from species'}"),
            ("Channels", str(cfg.regen.channels.count)),
            ("Coolant correlation", rs.coolant_correlation),
            ("Inlet T / p", f"{rs.inlet.temperature_K:.1f} K / {rs.inlet.pressure_bar:.1f} bar"
             f" ({rs.inlet.location})"),
            ("Wall material", rs.wall.material),
            ("Bartz correction", f"{rs.hot_gas.bartz_correction:g}"
             + (f" +/- {rs.hot_gas.bartz_correction_tol:g}" if rs.hot_gas.bartz_correction_tol else "")),
            ("Hot-gas property basis", rs.hot_gas.property_basis),
        ]))
    story.append(PageBreak())


def _combustion_section(story, styles, res: EngineResult) -> None:
    comb = res.combustion
    story.append(Paragraph("Combustion properties (nominal O/F)", styles["h1"]))
    rows = [
        ("Source", comb.source),
        ("Oxidizer state", comb.ox_state or "-"),
        ("Fuel state", comb.fuel_state or "-"),
        ("Nozzle expansion model", comb.nozzle_flow),
        ("Ideal c*", f"{comb.cstar_ideal_m_s:.1f} m/s"),
        ("Chamber temperature Tc", f"{comb.tc_K:.1f} K"),
        ("Gamma (chamber)", f"{comb.gamma:.4f}"),
        ("Mean molecular weight", f"{comb.mw_kg_kmol:.3f} kg/kmol"),
        ("R specific", f"{comb.R_specific:.1f} J/kg/K"),
    ]
    if comb.has_transport:
        rows += [
            ("Viscosity (chamber)", f"{comb.mu_Pa_s:.3e} Pa s"),
            ("cp frozen / equilibrium",
             f"{comb.cp_frozen_J_kgK:.0f} / {comb.cp_eq_J_kgK or float('nan'):.0f} J/kg/K"),
            ("Pr frozen / equilibrium",
             f"{comb.pr_frozen:.3f} / {comb.pr_eq or float('nan'):.3f}"),
        ]
    story.append(_kv_table(rows))
    nr = res.nozzle_reference
    if nr is not None:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(f"Ideal vacuum Isp band at eps = {nr.eps:.1f} (no efficiencies)", styles["h2"]))
        story.append(_kv_table([
            ("Single-gamma", f"{nr.isp_vac_single_gamma_s:.1f} s"),
            ("CEA equilibrium", f"{nr.isp_vac_equilibrium_s:.1f} s"),
            ("CEA frozen at throat", f"{nr.isp_vac_frozen_at_throat_s:.1f} s"),
            ("CEA frozen", f"{nr.isp_vac_frozen_s:.1f} s"),
            ("Selected model", nr.selected),
        ]))
    est = res.losses
    if est is not None:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Nozzle losses (first-order estimate)", styles["h2"]))
        story.append(_kv_table([
            ("Throat Reynolds number", f"{est.re_throat:.3e}"),
            ("Wall-shear thrust loss", f"{est.bl_loss_fraction * 100:.2f} %"),
            ("Laminar fraction of wetted length", f"{est.laminar_fraction * 100:.0f} %"),
            ("Divergence efficiency", f"{est.divergence_efficiency:.4f}"),
            ("eta_CF estimate / used", f"{est.eta_cf_estimate:.4f} / {est.eta_cf_used:.4f}"),
            ("Method", est.method),
        ]))
    cp = res.coupling
    if cp is not None:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Coupling loop", styles["h2"]))
        story.append(_kv_table([
            ("Iterations", f"{cp.iterations} ({'converged' if cp.converged else 'NOT converged'})"),
            ("Fuel / ox temperature used", f"{cp.fuel_temp_K:.1f} K / {cp.ox_temp_K:.1f} K"),
            ("Regen outlet feeds", f"{cp.coupled_side or '-'}"
             + (f" ({cp.regen_outlet_T_K:.1f} K)" if cp.regen_outlet_T_K else "")),
            ("eta_CF", f"{cp.eta_cf:.4f}" if cp.eta_cf is not None else "input"),
        ]))
    story.append(Spacer(1, 6 * mm))


def _uncertainty_section(story, styles, res: EngineResult) -> None:
    u = res.uncertainty
    if u is None:
        return
    tc = res.thrust_chamber
    story.append(Paragraph(
        f"Uncertainty band (eta_c* = {tc.eta_cstar:.3f} +/- {u.eta_tol:.3f})",
        styles["h1"],
    ))
    rows = [["Quantity", "Low (eta - tol)", "Nominal", "High (eta + tol)"]]
    for label, attr, fmt in [
        ("Isp [s]", "isp_s", "{:.2f}"),
        ("Pc [bar]", "pc_bar", "{:.2f}"),
        ("Thrust [N]", "thrust_N", "{:.0f}"),
        ("Total mdot [g/s]", "mdot_total_kg_s", None),
    ]:
        lo, nom, hi = (getattr(x, attr) for x in (u.tc_lo, tc, u.tc_hi))
        if abs(hi - lo) < 1e-12:
            continue
        if attr == "mdot_total_kg_s":
            lo, nom, hi = lo * 1e3, nom * 1e3, hi * 1e3
            fmt = "{:.1f}"
        rows.append([label, fmt.format(lo), fmt.format(nom), fmt.format(hi)])
    if len(rows) > 1:
        story.append(_table(rows, col_widths=[40 * mm, 40 * mm, 40 * mm, 40 * mm]))
        if res.mode == "design":
            story.append(Paragraph(
                "Design-mode eta_c* bounds re-size the engine (same thrust/Pc "
                "targets). Off-design bands keep the nominal geometry and only "
                "vary eta_c*.",
                styles["small"],
            ))
        story.append(Spacer(1, 6 * mm))


def _offdesign_summary(story, styles, res: EngineResult) -> None:
    od = res.offdesign
    if od is None:
        return
    story.append(Paragraph("Off-design sweeps (summary)", styles["h1"]))
    bullets = []
    if od.ox_throttle is not None:
        s = od.ox_throttle
        ok = ~s.separated
        F, pc = (a[ok] if ok.any() else a for a in (s.thrust_N, s.pc_bar))
        bullets.append(
            f"Ox throttle ({len(s.of)} pts): thrust {F.min():.0f}–{F.max():.0f} N, "
            f"Pc {pc.min():.1f}–{pc.max():.1f} bar"
        )
    if od.of_sweep is not None:
        s = od.of_sweep
        i = int(s.isp_s.argmax())
        bullets.append(
            f"O/F sweep: max Isp {s.isp_s[i]:.1f} s at O/F {s.of[i]:.2f}"
        )
    if od.envelope is not None:
        bullets.append("2-D envelope: Isp heatmap with Pc contours")
    for b in bullets:
        story.append(Paragraph(f"• {b}", styles["body"]))
    story.append(Spacer(1, 6 * mm))


def _regen_section(story, styles, res: EngineResult, cfg: EngineConfig) -> None:
    rg = res.regen
    if rg is None:
        return
    story.append(Paragraph("Regen cooling analysis", styles["h1"]))
    if rg.results is not None:
        s = rg.summary()
        a = rg.results.attrs
        rows = [
            ("Tag", rg.tag),
            ("Coolant side / flow", f"{s['coolant_side'] or '?'} / {s['mdot_coolant_kg_s'] * 1e3:.2f} g/s"),
            ("Hot-gas properties", str(a.get("hot_gas_property_note", ""))),
            ("Total heat load Q", f"{s['Q_total_kW']:.2f} kW"),
            ("Pressure drop", f"{s['dp_bar']:.3f} bar"),
            ("Outlet state", f"{s['outlet_T_K']:.1f} K / {s['outlet_p_bar']:.1f} bar"),
            ("Max hot wall temperature", f"{s['T_wall_max_K']:.0f} K"),
            ("Wall limit / margin",
             f"{s['T_wall_limit_K']:.0f} K ({a.get('wall_limit_source')}) / {s['wall_margin_K']:.0f} K"),
            ("Coolant Re range", f"{rg.results.Re.min():.0f} - {rg.results.Re.max():.0f}"),
            ("Coolant Mach max", f"{s['coolant_mach_max']:.3f}"),
            ("Saturation reached", "yes" if s.get("saturation_reached") else "no"),
            ("Wall-solve fallbacks", str(s.get("wall_solve_fallbacks", 0))),
        ]
        if rg.band is not None:
            rows.append(("T_wall,max band (Bartz +/- tol)",
                         f"{rg.band['lo']['T_wall_max_K']:.0f} - {rg.band['hi']['T_wall_max_K']:.0f} K"
                         f" (tol {rg.band['tol']:g})"))
        if "stress_ratio_max" in s:
            rows.append(("Hot-wall stress / yield (first-order)",
                         f"{s['sigma_max_MPa']:.0f} MPa, ratio {s['stress_ratio_max']:.2f}, "
                         f"strain {s['thermal_strain_max'] * 100:.2f} %"))
        if rg.feed_budget is not None:
            fb = rg.feed_budget
            rows.append(("Feed-pressure margin",
                         f"{fb['margin_bar']:.2f} bar (outlet {fb['outlet_p_bar']:.2f} vs required "
                         f"{fb['required_p_bar']:.2f} bar)"))
        if rg.skirt is not None:
            sk = rg.skirt.attrs
            rows.append(("Radiation-cooled skirt",
                         f"T_wall {sk['T_wall_max_K']:.0f} K max, {sk['T_wall_exit_K']:.0f} K at exit, "
                         f"{sk['Q_radiated_kW']:.2f} kW radiated"))
        story.append(_kv_table(rows))
    if cfg.regen is not None:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Regen sync flags", styles["h2"]))
        sync = cfg.regen.sync
        story.append(_kv_table([
            ("Contour from engine", "yes" if sync.contour else "no"),
            ("Hot-gas sync", "yes" if sync.hot_gas_pc_bar else "manual"),
            ("O/F sync", "yes" if sync.of_ratio else "no"),
            ("Mdot sync", "yes" if sync.mdot else "no"),
            ("Channels", str(cfg.regen.channels.count)),
            ("Coolant", cfg.regen.solver.coolant),
            ("Inlet location", cfg.regen.solver.inlet.location),
        ]))
    story.append(Spacer(1, 6 * mm))


def _film_section(story, styles, res: EngineResult) -> None:
    film = res.film
    if film is None:
        return
    story.append(Paragraph("Film cooling (first-order)", styles["h1"]))
    story.append(_kv_table([
        ("Side / fraction", f"{film.side} / {film.fraction:.3f}"),
        ("O/F overall → core", f"{film.of_overall:.3f} → {film.of_core:.3f}"),
        ("Film mass flow", f"{film.mdot_film_kg_s * 1e3:.1f} g/s"),
        ("Tank-side total", f"{film.mdot_total_kg_s * 1e3:.1f} g/s"),
        ("Isp core / delivered",
         f"{film.isp_core_s:.2f} / {film.isp_delivered_s:.2f} s"),
    ]))
    story.append(Spacer(1, 6 * mm))


def _config_appendix(story, styles, cfg_yaml: str) -> None:
    story.append(Paragraph("Appendix — resolved configuration", styles["h1"]))
    story.append(Paragraph(
        "Full YAML snapshot (also saved as config_resolved.yaml in the report folder).",
        styles["body"],
    ))
    story.append(Spacer(1, 3 * mm))
    # Split long yaml into chunks for readability
    lines = cfg_yaml.rstrip().splitlines()
    chunk = []
    for line in lines:
        chunk.append(_esc(line))
        if len(chunk) >= 55:
            story.append(Paragraph("<br/>".join(chunk), styles["small"]))
            story.append(Spacer(1, 2 * mm))
            chunk = []
    if chunk:
        story.append(Paragraph("<br/>".join(chunk), styles["small"]))


def write_pdf_report(
    res: EngineResult,
    cfg: EngineConfig,
    cfg_path: str | Path,
    outdir: Path,
    cfg_yaml: str | None = None,
) -> Path:
    """Build a readable PDF report with inputs, results, and static plots."""
    outdir = Path(outdir)
    pdf_path = outdir / "report.pdf"
    styles = _styles()
    story = []

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(_para(res.engine, styles["title"]))
    story.append(Paragraph(
        f"{_esc(res.mode.upper())} mode analysis report<br/>"
        f"config hash: {_esc(res.config_hash)}<br/>"
        f"config: {_esc(Path(cfg_path).as_posix())}<br/>"
        f"generated: {_esc(ts)}",
        styles["subtitle"],
    ))
    story.append(Spacer(1, 4 * mm))

    if res.warnings:
        story.append(Paragraph("Warnings", styles["h1"]))
        for w in res.warnings:
            story.append(_para(f"• {w}", styles["warn"]))
        story.append(Spacer(1, 6 * mm))

    _summary_section(story, styles, res)
    _inputs_section(story, styles, cfg)
    _combustion_section(story, styles, res)
    _uncertainty_section(story, styles, res)
    _film_section(story, styles, res)
    _offdesign_summary(story, styles, res)
    _regen_section(story, styles, res, cfg)

    story.append(Paragraph("Figures", styles["h1"]))
    story.append(Paragraph(
        "Static plots for print/PDF review. Interactive HTML plots are in the "
        "same report folder.",
        styles["body"],
    ))
    story.append(PageBreak())

    tc = res.thrust_chamber
    u = res.uncertainty

    if res.contour is not None:
        _plot_page(story, styles, "Chamber contour",
                   pdf_plots.contour_figure(res.contour, title=res.engine))
        _plot_page(story, styles, "Mach distribution",
                   pdf_plots.mach_figure(res.contour))

    od = res.offdesign
    if od is not None:
        if od.ox_throttle is not None:
            band = None
            if u is not None and u.od_lo is not None and u.od_lo.ox_throttle:
                band = (u.od_lo.ox_throttle, u.od_hi.ox_throttle)
            _plot_page(story, styles, "Ox-only throttle sweep",
                       pdf_plots.ox_throttle_figure(
                           od.ox_throttle, nominal=tc, band=band))
        if od.of_sweep is not None:
            band = None
            if u is not None and u.od_lo is not None and u.od_lo.of_sweep:
                band = (u.od_lo.of_sweep, u.od_hi.of_sweep)
            _plot_page(story, styles, "O/F sweep",
                       pdf_plots.of_sweep_figure(
                           od.of_sweep, nominal=tc, band=band))
        if od.envelope is not None:
            _plot_page(story, styles, "Operating envelope",
                       pdf_plots.envelope_figure(od.envelope, nominal=tc))

    if res.regen is not None:
        lay = res.regen.layout
        _plot_page(story, styles, "Regen channel geometry",
                   pdf_plots.regen_geometry_figure(lay))
        if res.regen.results is not None and cfg.regen is not None:
            _plot_page(
                story, styles, "Regen thermal-hydraulic results",
                pdf_plots.regen_results_figure(
                    res.regen.results, res.regen.results.attrs.get("wall_limit_K", 1200.0),
                ),
            )

    if cfg_yaml is None:
        cfg_yaml = yaml.safe_dump(cfg.model_dump(), sort_keys=False)
    story.append(PageBreak())
    _config_appendix(story, styles, cfg_yaml)

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"{res.engine} — RESA report",
        author="RESA",
    )
    doc.build(story)
    return pdf_path
