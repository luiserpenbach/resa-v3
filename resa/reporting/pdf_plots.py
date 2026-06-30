"""Matplotlib figures for PDF reports — print-friendly, one concept per axes."""
from __future__ import annotations

from io import BytesIO

import matplotlib.pyplot as plt
import numpy as np

from ..results import ContourResult, EnvelopeResult

_STYLE = dict(figsize=(7.0, 4.0), dpi=150)
_FONT = dict(labelsize=9, titlesize=10)


def _setup():
    plt.rcParams.update({
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "legend.fontsize": 8,
        "figure.dpi": 150,
    })


def figure_to_bytes(fig) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def contour_figure(c: ContourResult, title: str = "") -> bytes:
    _setup()
    fig, ax = plt.subplots(figsize=_STYLE["figsize"])
    x, r = c.x_m * 1e3, c.r_m * 1e3
    ax.plot(x, r, color="#1f77b4", lw=1.8, label="wall")
    ax.plot(x, -r, color="#1f77b4", lw=1.8)
    ax.axvline(0, color="#d62728", ls=":", lw=1)
    ax.plot(0, c.throat_radius_m * 1e3, "o", color="#d62728", ms=5)
    ax.set_title(title or f"Chamber contour ({c.method})")
    ax.set_xlabel("Axial x [mm]")
    ax.set_ylabel("Radius [mm]")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.25)
    return figure_to_bytes(fig)


def mach_figure(c: ContourResult) -> bytes:
    _setup()
    fig, ax1 = plt.subplots(figsize=_STYLE["figsize"])
    x = c.x_m * 1e3
    ax1.plot(x, c.mach, color="#2ca02c", lw=1.8, label="Mach")
    ax1.axhline(1.0, color="#d62728", ls="--", lw=1)
    ax1.set_xlabel("Axial x [mm]")
    ax1.set_ylabel("Mach [-]")
    ax2 = ax1.twinx()
    ax2.plot(x, c.r_m * 1e3, color="#1f77b4", ls=":", lw=1.2, label="radius")
    ax2.set_ylabel("Radius [mm]")
    ax1.set_title("Quasi-1D Mach distribution")
    ax1.grid(True, alpha=0.25)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)
    return figure_to_bytes(fig)


def ox_throttle_figure(s, nominal=None, band=None) -> bytes:
    _setup()
    fig, ax1 = plt.subplots(figsize=_STYLE["figsize"])
    x = s.mdot_ox_kg_s * 1e3
    if band is not None:
        lo, hi = band
        ax1.fill_between(x, lo.thrust_N, hi.thrust_N, color="#1f77b4", alpha=0.15,
                         label="eta_c* band")
    ax1.plot(x, s.thrust_N, "o-", color="#1f77b4", ms=3, lw=1.5, label="thrust")
    if s.separated.any():
        ax1.plot(x[s.separated], s.thrust_N[s.separated], "x", color="#d62728",
                 ms=6, label="separation risk")
    if nominal is not None:
        ax1.axvline(nominal.mdot_ox_kg_s * 1e3, color="#2ca02c", ls=":", lw=1)
    ax2 = ax1.twinx()
    ax2.plot(x, s.pc_bar, "--", color="#ff7f0e", lw=1.5, label="Pc")
    ax1.set_xlabel("Ox mass flow [g/s]")
    ax1.set_ylabel("Thrust [N]")
    ax2.set_ylabel("Pc [bar]")
    ax1.set_title("Ox-only throttle (fuel constant)")
    ax1.grid(True, alpha=0.25)
    return figure_to_bytes(fig)


def of_sweep_figure(s, nominal=None, band=None) -> bytes:
    _setup()
    fig, ax1 = plt.subplots(figsize=_STYLE["figsize"])
    if band is not None:
        lo, hi = band
        ax1.fill_between(s.of, lo.isp_s, hi.isp_s, color="#1f77b4", alpha=0.15)
    ax1.plot(s.of, s.isp_s, color="#1f77b4", lw=1.8, label="Isp")
    i = int(s.isp_s.argmax())
    ax1.plot(s.of[i], s.isp_s[i], "o", color="#d62728", ms=6)
    if nominal is not None:
        ax1.axvline(nominal.of_ratio, color="#2ca02c", ls=":", lw=1)
    ax2 = ax1.twinx()
    ax2.plot(s.of, s.cstar_eff_m_s, "--", color="#ff7f0e", lw=1.5, label="c* eff")
    ax1.set_xlabel("O/F [-]")
    ax1.set_ylabel("Isp [s]")
    ax2.set_ylabel("c* effective [m/s]")
    ax1.set_title("O/F sweep (constant total mdot)")
    ax1.grid(True, alpha=0.25)
    return figure_to_bytes(fig)


def envelope_figure(e: EnvelopeResult, nominal=None) -> bytes:
    _setup()
    fig, ax = plt.subplots(figsize=(7.0, 4.8))
    z = e.isp_s.copy().astype(float)
    z[e.separated] = np.nan
    throttle_pct = e.throttle_frac * 100
    extent = [throttle_pct[0], throttle_pct[-1], e.of[0], e.of[-1]]
    im = ax.imshow(
        z.T, origin="lower", aspect="auto", extent=extent, cmap="viridis",
    )
    ax.contour(
        throttle_pct, e.of, e.pc_bar, colors="white", linewidths=0.6, alpha=0.7,
    )
    if nominal is not None:
        ax.plot(100.0, nominal.of_ratio, "*", color="#d62728", ms=10)
    ax.set_xlabel("Total-flow throttle [%]")
    ax.set_ylabel("O/F [-]")
    ax.set_title("Operating envelope (Isp; blank = separation risk)")
    fig.colorbar(im, ax=ax, label="Isp [s]", shrink=0.85)
    return figure_to_bytes(fig)


def regen_geometry_figure(lay) -> bytes:
    _setup()
    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.5), sharex=True)
    x = lay.x * 1e3
    ax = axes[0, 0]
    ax.plot(x, lay.r * 1e3, label="hot wall", color="#444")
    ax.plot(x, (lay.r + lay.t_wall) * 1e3, ls=":", label="floor")
    ax.plot(x, (lay.r + lay.t_wall + lay.h) * 1e3, ls=":", label="top")
    ax.set_ylabel("Radius [mm]")
    ax.set_title("Contour & channel envelope")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.25)

    ax = axes[0, 1]
    ax.plot(x, np.degrees(lay.beta), color="#d97706", label="helix beta")
    ax2 = ax.twinx()
    ax2.plot(x, np.degrees(lay.theta), color="#2563eb", label="wrap")
    ax.set_ylabel("Helix [deg]")
    ax2.set_ylabel("Wrap [deg]")
    ax.set_title("Helix & wrap")
    ax.grid(True, alpha=0.25)

    ax = axes[1, 0]
    ax.plot(x, lay.w * 1e3, label="width")
    ax.plot(x, lay.h * 1e3, label="height")
    ax.plot(x, lay.t_rib * 1e3, label="rib")
    ax.set_xlabel("Axial x [mm]")
    ax.set_ylabel("Size [mm]")
    ax.set_title("Cross-section")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.25)

    ax = axes[1, 1]
    ax.plot(x, lay.A * 1e6, label="A")
    ax.plot(x, lay.Dh * 1e3, label="Dh")
    ax.set_xlabel("Axial x [mm]")
    ax.set_ylabel("Area / Dh")
    ax.set_title("Hydraulics")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.25)

    fig.suptitle("Regen channel geometry", fontsize=11, y=1.02)
    fig.tight_layout()
    return figure_to_bytes(fig)


def regen_results_figure(df, max_wall_T: float) -> bytes:
    _setup()
    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.5), sharex=True)
    x = df.x_m * 1e3

    ax = axes[0, 0]
    ax.plot(x, df.T_wall_hot_K, label="T wall hot", color="#dc2626")
    ax.plot(x, df.T_wall_cold_K, label="T wall cold", color="#ea580c")
    ax.plot(x, df.T_cool_K, label="T coolant", color="#2563eb")
    ax.axhline(max_wall_T, ls="--", color="#991b1b", lw=1, label="limit")
    ax.set_ylabel("Temperature [K]")
    ax.set_title("Wall & coolant temperatures")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.25)

    ax = axes[0, 1]
    ax.plot(x, df.q_w_W_m2 / 1e6, color="#7c3aed")
    ax.set_ylabel("q'' [MW/m²]")
    ax.set_title("Heat flux")
    ax.grid(True, alpha=0.25)

    ax = axes[1, 0]
    ax.plot(x, df.p_cool_bar, color="#0d9488")
    ax.set_xlabel("Axial x [mm]")
    ax.set_ylabel("p coolant [bar]")
    ax.set_title("Coolant pressure")
    ax.grid(True, alpha=0.25)

    ax = axes[1, 1]
    ax.plot(x, df.v_m_s, label="v coolant")
    ax.plot(x, df.mach, ls=":", label="gas Mach")
    ax.set_xlabel("Axial x [mm]")
    ax.set_ylabel("Velocity / Mach")
    ax.set_title("Velocities")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.25)

    fig.suptitle("Regen thermal-hydraulic results", fontsize=11, y=1.02)
    fig.tight_layout()
    return figure_to_bytes(fig)
