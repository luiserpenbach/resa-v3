"""Plotly visualization: interactive 3D channel geometry (optionally colored
by solver results) and a 2D results / geometry dashboard.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .coolant import Coolant
from .layout import ChannelLayout
from .mesh import build_channel_mesh, channel_centerline, inner_wall_surface

MM = 1e3


def figure_3d(lay: ChannelLayout, results=None, color_by: str = "T_wall_hot",
              max_channels_full: int = 64,
              channel_ids: list[int] | None = None) -> go.Figure:
    col_map = {"T_wall_hot": "T_wall_hot_K", "T_wall_cold": "T_wall_cold_K",
               "T_cool": "T_cool_K", "q_w": "q_w_W_m2", "p_cool": "p_cool_bar",
               "v": "v_m_s"}
    scalar, cbar_title = None, None
    if results is not None and color_by != "channel":
        col = col_map.get(color_by, color_by)
        if col in results.columns:
            scalar = results.sort_values("x_m")[col].to_numpy()
            cbar_title = col

    if channel_ids is None:
        ids = list(range(min(lay.N, max_channels_full)))
    else:
        ids = list(channel_ids)

    verts, faces, inten = build_channel_mesh(lay, ids, scalar=scalar)

    fig = go.Figure()
    # hot wall context surface
    X, Y, Z = inner_wall_surface(lay)
    fig.add_trace(go.Surface(
        x=X * MM, y=Y * MM, z=Z * MM, opacity=0.25, showscale=False,
        colorscale=[[0, "#888"], [1, "#bbb"]], name="hot wall",
        hoverinfo="skip"))

    mesh_kw = dict(
        x=verts[:, 0] * MM, y=verts[:, 1] * MM, z=verts[:, 2] * MM,
        i=faces[:, 0], j=faces[:, 1], k=faces[:, 2],
        flatshading=True, name="channels")
    if inten is not None:
        mesh_kw.update(intensity=inten, colorscale="Turbo",
                       colorbar=dict(title=cbar_title, len=0.7))
    else:
        mesh_kw.update(color="#d97706")
    fig.add_trace(go.Mesh3d(**mesh_kw))

    # one highlighted centerline to read the wrap
    highlight = ids[0] if ids else 0
    cl = channel_centerline(lay, highlight)
    fig.add_trace(go.Scatter3d(
        x=cl[:, 0] * MM, y=cl[:, 1] * MM, z=cl[:, 2] * MM,
        mode="lines", line=dict(color="black", width=5),
        name=f"centerline ch {highlight}"))

    fig.update_layout(
        title="Regen channel geometry"
              + (f" — colored by {cbar_title}" if inten is not None else ""),
        scene=dict(aspectmode="data",
                   xaxis_title="x [mm]", yaxis_title="y [mm]",
                   zaxis_title="z [mm]"),
        template="plotly_white", margin=dict(l=0, r=0, t=40, b=0))
    return fig


def figure_geometry(lay: ChannelLayout) -> go.Figure:
    x = lay.x * MM
    fig = make_subplots(
        rows=2, cols=2, shared_xaxes=True,
        subplot_titles=("Contour & channel envelope",
                        "Helix angle & wrap",
                        "Channel cross-section",
                        "Flow area & hydraulic diameter"))
    fig.add_trace(go.Scatter(x=x, y=lay.r * MM, name="r hot wall",
                             line=dict(color="#444")), 1, 1)
    fig.add_trace(go.Scatter(x=x, y=(lay.r + lay.t_wall) * MM,
                             name="channel floor", line=dict(dash="dot")), 1, 1)
    fig.add_trace(go.Scatter(x=x, y=(lay.r + lay.t_wall + lay.h) * MM,
                             name="channel top", line=dict(dash="dot")), 1, 1)
    fig.add_trace(go.Scatter(x=x, y=np.degrees(lay.beta), name="beta [deg]",
                             line=dict(color="#d97706")), 1, 2)
    fig.add_trace(go.Scatter(x=x, y=np.degrees(lay.theta),
                             name="wrap theta [deg]", yaxis="y4",
                             line=dict(color="#2563eb")), 1, 2)
    fig.add_trace(go.Scatter(x=x, y=lay.w * MM, name="width w"), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=lay.h * MM, name="height h"), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=lay.t_rib * MM, name="rib t"), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=lay.A * 1e6, name="A [mm2]"), 2, 2)
    fig.add_trace(go.Scatter(x=x, y=lay.Dh * MM, name="Dh [mm]"), 2, 2)
    fig.update_xaxes(title_text="x [mm]", row=2)
    fig.update_layout(title="Channel geometry profiles",
                      template="plotly_white", height=720)
    return fig


def figure_results(df, lay: ChannelLayout, max_wall_T: float) -> go.Figure:
    x = df.x_m * MM
    fig = make_subplots(
        rows=3, cols=2, shared_xaxes=True, vertical_spacing=0.07,
        subplot_titles=("Wall & coolant temperatures", "Heat flux",
                        "Coolant pressure", "Coolant velocity & Mach",
                        "Film coefficients", "Coolant T vs T_sat"))
    fig.add_trace(go.Scatter(x=x, y=df.T_wall_hot_K, name="T_wall hot",
                             line=dict(color="#dc2626")), 1, 1)
    fig.add_trace(go.Scatter(x=x, y=df.T_wall_cold_K, name="T_wall cold",
                             line=dict(color="#ea580c")), 1, 1)
    fig.add_trace(go.Scatter(x=x, y=df.T_cool_K, name="T coolant",
                             line=dict(color="#2563eb")), 1, 1)
    fig.add_hline(y=max_wall_T, line_dash="dash", line_color="#991b1b",
                  annotation_text="wall limit", row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=df.q_w_W_m2 / 1e6, name="q'' [MW/m2]",
                             line=dict(color="#7c3aed")), 1, 2)
    fig.add_trace(go.Scatter(x=x, y=df.p_cool_bar, name="p coolant [bar]",
                             line=dict(color="#0d9488")), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=df.v_m_s, name="v coolant [m/s]"), 2, 2)
    fig.add_trace(go.Scatter(x=x, y=df.mach, name="hot-gas Mach",
                             line=dict(dash="dot")), 2, 2)
    fig.add_trace(go.Scatter(x=x, y=df.h_g, name="h_g [W/m2K]"), 3, 1)
    fig.add_trace(go.Scatter(x=x, y=df.h_c, name="h_c [W/m2K]"), 3, 1)
    fig.add_trace(go.Scatter(x=x, y=df.T_cool_K, name="T coolant",
                             showlegend=False, line=dict(color="#2563eb")), 3, 2)
    fig.add_trace(go.Scatter(x=x, y=df.T_sat_K, name="T_sat(p)",
                             line=dict(color="#9333ea", dash="dash")), 3, 2)
    fig.update_xaxes(title_text="x [mm]", row=3)
    a = df.attrs
    fig.update_layout(
        title=(f"Regen solve — Q_total {a.get('Q_total_kW', 0):.1f} kW, "
               f"dp {df.dp_cell_bar.sum():.1f} bar, "
               f"outlet {a.get('outlet_T_K', 0):.0f} K / "
               f"{a.get('outlet_p_bar', 0):.1f} bar, "
               f"mdot_cool {a.get('mdot_total', 0):.3f} kg/s"),
        template="plotly_white", height=950)
    return fig


def _coolant_path_df(df, inlet_location: str):
    """Rows in coolant march order (inlet → outlet)."""
    if inlet_location == "nozzle_end":
        return df.sort_values("x_m", ascending=False).reset_index(drop=True)
    return df.sort_values("x_m").reset_index(drop=True)


def _saturation_traces(cool: Coolant, pressures_bar: list[float]) -> list[go.Scatter]:
    """Bubble (Q=0) and dew (Q=1) lines in T–ρ at subcritical pressures."""
    from CoolProp.CoolProp import PropsSI

    traces: list[go.Scatter] = []
    shown = False
    for p_bar in sorted(set(pressures_bar)):
        p = p_bar * 1e5
        if p >= cool.p_crit:
            continue
        try:
            T_sat = PropsSI("T", "P", p, "Q", 0, cool.cp_name)
            T_lo = max(float(PropsSI("Tmin", cool.cp_name)) + 1.0, 180.0)
            Ts = np.linspace(T_lo, T_sat, 50)
            rho_l = [PropsSI("D", "T", T, "Q", 0, cool.cp_name) for T in Ts]
            rho_v = [PropsSI("D", "T", T, "Q", 1, cool.cp_name) for T in Ts]
        except Exception:
            continue
        traces.append(go.Scatter(
            x=Ts, y=rho_l, mode="lines",
            line=dict(color="#94a3b8", width=1, dash="dot"),
            name=f"Q=0 @ {p_bar:.0f} bar",
            legendgroup="sat", showlegend=not shown))
        traces.append(go.Scatter(
            x=Ts, y=rho_v, mode="lines",
            line=dict(color="#cbd5e1", width=1, dash="dash"),
            name=f"Q=1 @ {p_bar:.0f} bar",
            legendgroup="sat", showlegend=False))
        shown = True
    return traces


def figure_coolant_path(
    df,
    coolant_name: str,
    inlet_location: str | None = None,
) -> go.Figure:
    """Coolant state path on T–ρ axes plus axial profiles along the circuit."""
    cool = Coolant(coolant_name)
    loc = inlet_location or df.attrs.get("coolant_inlet_location", "nozzle_end")
    path = _coolant_path_df(df, loc)
    a = df.attrs

    T = path.T_cool_out_K.to_numpy()
    rho = path.rho_out.to_numpy()
    x_mm = path.x_m.to_numpy() * MM
    p_bar = path.p_cool_out_bar.to_numpy()

    fig = make_subplots(
        rows=1, cols=2, column_widths=[0.55, 0.45],
        subplot_titles=("Coolant path in T–ρ space",
                        "Bulk coolant along the channel"),
        horizontal_spacing=0.08)

    p_in = float(path.p_cool_bar.iloc[0])
    p_out = float(path.p_cool_out_bar.iloc[-1])
    for tr in _saturation_traces(cool, sorted({p_in, p_out, 60.0, 90.0})):
        fig.add_trace(tr, row=1, col=1)

    try:
        from CoolProp.CoolProp import PropsSI
        fig.add_trace(go.Scatter(
            x=[cool.T_crit], y=[PropsSI("D", "T", cool.T_crit, "P", cool.p_crit,
                                        cool.cp_name)],
            mode="markers", marker=dict(size=10, color="#64748b", symbol="x"),
            name="critical point"), row=1, col=1)
    except Exception:
        pass

    fig.add_trace(go.Scatter(
        x=T, y=rho, mode="lines+markers",
        line=dict(color="#2563eb", width=2),
        marker=dict(size=5, color=x_mm, colorscale="Turbo",
                    colorbar=dict(title="x [mm]", len=0.85, x=0.46),
                    showscale=True),
        name="coolant path",
        hovertemplate=("T=%{x:.1f} K<br>ρ=%{y:.1f} kg/m³<br>"
                       "<extra></extra>")), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=[path.T_cool_K.iloc[0]], y=[path.rho.iloc[0]],
        mode="markers", marker=dict(size=12, color="#16a34a", symbol="circle"),
        name="inlet"), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=[T[-1]], y=[rho[-1]],
        mode="markers", marker=dict(size=12, color="#dc2626", symbol="diamond"),
        name="outlet"), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=x_mm, y=path.T_cool_K, name="T inlet (cell)",
        line=dict(color="#93c5fd", dash="dot")), row=1, col=2)
    fig.add_trace(go.Scatter(
        x=x_mm, y=T, name="T outlet (cell)",
        line=dict(color="#2563eb")), row=1, col=2)
    fig.add_trace(go.Scatter(
        x=x_mm, y=path.T_sat_K, name="T_sat(p)",
        line=dict(color="#9333ea", dash="dash")), row=1, col=2)
    fig.add_trace(go.Scatter(
        x=x_mm, y=p_bar, name="p [bar]", yaxis="y4",
        line=dict(color="#0d9488")), row=1, col=2)

    dh = a.get("dh_kJ_kg", 0.0)
    bal = a.get("energy_balance_kW", 0.0)
    fig.update_xaxes(title_text="T [K]", row=1, col=1)
    fig.update_yaxes(title_text="ρ [kg/m³]", row=1, col=1)
    fig.update_xaxes(title_text="x [mm]", row=1, col=2)
    fig.update_yaxes(title_text="T [K]", row=1, col=2)
    fig.update_layout(
        title=(f"Coolant circuit — Δh={dh:.0f} kJ/kg, "
               f"Q={a.get('Q_total_kW', 0):.1f} kW, "
               f"mdot={a.get('mdot_total', 0):.3f} kg/s, "
               f"energy closure {bal:.2e} kW"),
        template="plotly_white", height=520, margin=dict(t=60),
        yaxis4=dict(title="p [bar]", overlaying="y2", side="right",
                    anchor="x2", showgrid=False))
    return fig
