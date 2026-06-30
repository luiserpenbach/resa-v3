"""Plotly figures. Pure: take results, return go.Figure. No file writing here.

The report writer decides where figures go; these just build them.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from ..results import ContourResult


def contour_figure(c: ContourResult, title: str = "") -> go.Figure:
    """Full wetted contour, mirrored about the axis, equal aspect."""
    x = c.x_m * 1e3
    r = c.r_m * 1e3
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=r, mode="lines", line=dict(color="#1f77b4", width=2), name="wall"))
    fig.add_trace(go.Scatter(x=x, y=-r, mode="lines", line=dict(color="#1f77b4", width=2), showlegend=False))
    # markers at throat and exit
    fig.add_trace(go.Scatter(x=[0], y=[c.throat_radius_m * 1e3], mode="markers+text",
                             marker=dict(color="#d62728", size=8), text=["throat"],
                             textposition="top center", name="throat"))
    fig.add_vline(x=0, line=dict(color="#d62728", width=1, dash="dot"))
    fig.update_layout(
        title=title or f"Contour — {c.method}",
        xaxis_title="axial x [mm]", yaxis_title="radius [mm]",
        template="plotly_white", width=900, height=420,
        legend=dict(orientation="h", y=1.1),
    )
    fig.update_yaxes(scaleanchor="x", scaleratio=1.0)
    return fig


def mach_figure(c: ContourResult) -> go.Figure:
    """Quasi-1D Mach and radius vs axial position (dual axis)."""
    x = c.x_m * 1e3
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=c.mach, mode="lines", name="Mach",
                             line=dict(color="#2ca02c", width=2)))
    fig.add_trace(go.Scatter(x=x, y=c.r_m * 1e3, mode="lines", name="radius [mm]",
                             line=dict(color="#1f77b4", width=1, dash="dot"), yaxis="y2"))
    fig.add_hline(y=1.0, line=dict(color="#d62728", width=1, dash="dash"))
    fig.update_layout(
        title="Quasi-1D Mach distribution",
        xaxis_title="axial x [mm]", yaxis_title="Mach",
        yaxis2=dict(title="radius [mm]", overlaying="y", side="right"),
        template="plotly_white", width=900, height=360,
        legend=dict(orientation="h", y=1.15),
    )
    return fig


# ------------------------- off-design / throttle --------------------------- #
def _band(fig, x, lo, hi, rgba, name):
    """Shaded band between lo and hi arrays."""
    fig.add_trace(go.Scatter(x=x, y=hi, line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=lo, fill="tonexty", fillcolor=rgba,
                             line=dict(width=0), name=name, hoverinfo="skip"))


def ox_throttle_figure(s, nominal=None, band=None) -> go.Figure:
    """E2-style ox-only throttle line: thrust + Pc vs mdot_ox, O/F on hover,
    separation-risk points marked."""
    hover = [
        f"ṁ_ox {mo*1e3:.0f} g/s<br>O/F {of:.2f}<br>Pc {pc:.1f} bar"
        f"<br>Isp {isp:.1f} s" for mo, of, pc, isp in
        zip(s.mdot_ox_kg_s, s.of, s.pc_bar, s.isp_s)
    ]
    fig = go.Figure()
    if band is not None:
        s_lo, s_hi = band
        _band(fig, s.mdot_ox_kg_s * 1e3, s_lo.thrust_N, s_hi.thrust_N,
              "rgba(31,119,180,0.18)", "thrust η_c* band")
    fig.add_trace(go.Scatter(
        x=s.mdot_ox_kg_s * 1e3, y=s.thrust_N, mode="lines+markers",
        name="thrust [N]", line=dict(color="#1f77b4", width=2),
        text=hover, hoverinfo="text+y",
    ))
    fig.add_trace(go.Scatter(
        x=s.mdot_ox_kg_s * 1e3, y=s.pc_bar, mode="lines", name="Pc [bar]",
        line=dict(color="#ff7f0e", width=2, dash="dash"), yaxis="y2",
    ))
    if s.separated.any():
        m = s.separated
        fig.add_trace(go.Scatter(
            x=s.mdot_ox_kg_s[m] * 1e3, y=s.thrust_N[m], mode="markers",
            name="separation risk", marker=dict(color="#d62728", size=9,
                                                symbol="x"),
        ))
    if nominal is not None:
        fig.add_vline(x=nominal.mdot_ox_kg_s * 1e3,
                      line=dict(color="#2ca02c", dash="dot"),
                      annotation_text="nominal")
    fig.update_layout(
        title="Ox-only throttle (fuel constant)",
        xaxis_title="ṁ_ox [g/s]", yaxis_title="thrust [N]",
        yaxis2=dict(title="Pc [bar]", overlaying="y", side="right"),
        template="plotly_white", width=900, height=420,
        legend=dict(orientation="h", y=1.12),
    )
    return fig


def of_sweep_figure(s, nominal=None, band=None) -> go.Figure:
    """Isp and effective c* vs O/F at constant total mdot."""
    fig = go.Figure()
    if band is not None:
        s_lo, s_hi = band
        _band(fig, s.of, s_lo.isp_s, s_hi.isp_s,
              "rgba(31,119,180,0.18)", "Isp η_c* band")
    fig.add_trace(go.Scatter(x=s.of, y=s.isp_s, mode="lines", name="Isp [s]",
                             line=dict(color="#1f77b4", width=2)))
    fig.add_trace(go.Scatter(x=s.of, y=s.cstar_eff_m_s, mode="lines",
                             name="c*_eff [m/s]",
                             line=dict(color="#ff7f0e", width=2, dash="dash"),
                             yaxis="y2"))
    i_best = int(s.isp_s.argmax())
    fig.add_trace(go.Scatter(x=[s.of[i_best]], y=[s.isp_s[i_best]],
                             mode="markers+text", text=["max Isp"],
                             textposition="top center", showlegend=False,
                             marker=dict(color="#d62728", size=9)))
    if nominal is not None:
        fig.add_vline(x=nominal.of_ratio, line=dict(color="#2ca02c", dash="dot"),
                      annotation_text="nominal")
    fig.update_layout(
        title="O/F sweep (constant total ṁ, fixed geometry)",
        xaxis_title="O/F [-]", yaxis_title="Isp [s]",
        yaxis2=dict(title="c*_eff [m/s]", overlaying="y", side="right"),
        template="plotly_white", width=900, height=420,
        legend=dict(orientation="h", y=1.12),
    )
    return fig


def envelope_figure(e, nominal=None) -> go.Figure:
    """Operating envelope: Isp heatmap over throttle × O/F, Pc contour lines,
    separation region masked out, nominal point marked."""
    z = e.isp_s.copy()
    z[e.separated] = None                       # mask separated cells
    hover = [[
        (f"throttle {tf*100:.0f}%<br>O/F {of:.2f}<br>"
         + ("SEPARATION RISK (full-flow values invalid)"
            f"<br>Pc {pc:.1f} bar" if sp else
            f"Isp {isp:.1f} s<br>Pc {pc:.1f} bar<br>F {F:.0f} N"))
        for tf, isp, pc, F, sp in zip(e.throttle_frac, zi, pci, Fi, si)
    ] for of, zi, pci, Fi, si in
        zip(e.of, e.isp_s, e.pc_bar, e.thrust_N, e.separated)]
    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        x=e.throttle_frac * 100, y=e.of, z=z, colorscale="Viridis",
        colorbar=dict(title="Isp [s]"), text=hover, hoverinfo="text",
    ))
    fig.add_trace(go.Contour(
        x=e.throttle_frac * 100, y=e.of, z=e.pc_bar, showscale=False,
        contours=dict(coloring="lines", showlabels=True,
                      labelfont=dict(size=10, color="white")),
        line=dict(color="rgba(255,255,255,0.7)", width=1),
        name="Pc [bar]", hoverinfo="skip",
    ))
    if nominal is not None:
        fig.add_trace(go.Scatter(
            x=[100.0], y=[nominal.of_ratio], mode="markers+text",
            text=["nominal"], textposition="top center",
            marker=dict(color="#d62728", size=11, symbol="star"),
            showlegend=False,
        ))
    fig.update_layout(
        title=("Operating envelope — Isp heatmap, Pc contours "
               "(blank = separation risk)"),
        xaxis_title="total-flow throttle [%]", yaxis_title="O/F [-]",
        template="plotly_white", width=900, height=540,
    )
    return fig
