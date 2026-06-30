"""`regen diff` — compare two channel configs at three levels:

  1. Config:   recursive diff of the validated YAML (dotted paths, A -> B).
  2. Geometry: layouts rebuilt and compared on a common x grid — per-profile
               max/RMS deviation plus scalar summary (min width, throat
               section, wrap, path length, coolant volume, ...).
  3. Solver:   (--solve) both solved, key thermal/hydraulic scalars compared.

Usage:
    python -m regen_channels.diff A.yaml B.yaml [--solve] [--html out.html]

Plotly overlay report: solid = A, dashed = B.
"""
from __future__ import annotations

import argparse
import os
from typing import Any

import numpy as np

from .config import RegenConfig
from .contour import build_contour
from .layout import ChannelLayout

MM = 1e3


# ------------------------------------------------------------ config diff
def _flatten(d: Any, prefix: str = "") -> dict:
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    else:
        out[prefix] = d
    return out


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    s = str(v)
    return s if len(s) <= 60 else s[:57] + "..."


def diff_configs(a: RegenConfig, b: RegenConfig) -> list[tuple[str, str, str]]:
    fa, fb = _flatten(a.model_dump()), _flatten(b.model_dump())
    rows = []
    for key in sorted(set(fa) | set(fb)):
        va, vb = fa.get(key, "<absent>"), fb.get(key, "<absent>")
        if va == vb:
            continue
        if (isinstance(va, list) and isinstance(vb, list)
                and len(va) == len(vb)):
            for i, (ea, eb) in enumerate(zip(va, vb)):
                if ea != eb:
                    rows.append((f"{key}[{i}]", _fmt(ea), _fmt(eb)))
        else:
            rows.append((key, _fmt(va), _fmt(vb)))
    return rows


# ---------------------------------------------------------- geometry diff
GEO_PROFILES = [
    ("width_m", "channel width", MM, "mm"),
    ("height_m", "channel height", MM, "mm"),
    ("rib_m", "rib width", MM, "mm"),
    ("wall_m", "inner wall", MM, "mm"),
    ("beta_deg", "helix angle", 1.0, "deg"),
    ("Dh_m", "hydraulic dia", MM, "mm"),
    ("area_m2", "flow area", 1e6, "mm2"),
]


def _geo_scalars(lay: ChannelLayout) -> dict:
    j_t = int(np.argmin(np.abs(lay.x - lay.x_throat)))
    vol = float(np.sum(lay.A * lay.dl)) * lay.N
    return {
        "channel count": lay.N,
        "extent x [mm]": (lay.x[0] * MM, lay.x[-1] * MM),
        "min width [mm]": float(lay.w.min()) * MM,
        "width @throat [mm]": float(lay.w[j_t]) * MM,
        "height @throat [mm]": float(lay.h[j_t]) * MM,
        "Dh @throat [mm]": float(lay.Dh[j_t]) * MM,
        "area @throat [mm2]": float(lay.A[j_t]) * 1e6,
        "total wrap [deg]": float(np.degrees(lay.theta[-1])),
        "channel path length [mm]": float(lay.l[-1]) * MM,
        "coolant volume [cm3]": vol * 1e6,
        "mean hot coverage [-]": float(lay.coverage_fraction().mean()),
    }


def diff_layouts(la: ChannelLayout, lb: ChannelLayout):
    """Returns (scalar_rows, profile_rows, common_x). Profiles compared on
    the overlapping x extent (B interpolated onto A's grid)."""
    x0, x1 = max(la.x[0], lb.x[0]), min(la.x[-1], lb.x[-1])
    xa = la.x[(la.x >= x0) & (la.x <= x1)]
    da, db = la.to_dataframe(), lb.to_dataframe()

    profile_rows = []
    for col, label, scale, unit in GEO_PROFILES:
        va = np.interp(xa, da.x_m, da[col]) * scale
        vb = np.interp(xa, db.x_m, db[col]) * scale
        d = vb - va
        i = int(np.argmax(np.abs(d)))
        profile_rows.append((label, unit, float(np.abs(d).max()),
                             float(np.sqrt(np.mean(d * d))),
                             float(xa[i] * MM)))

    sa, sb = _geo_scalars(la), _geo_scalars(lb)
    scalar_rows = []
    for k in sa:
        va, vb = sa[k], sb[k]
        if isinstance(va, tuple):
            same = np.allclose(va, vb, atol=1e-9)
            scalar_rows.append((k, f"{va[0]:.1f}..{va[1]:.1f}",
                                f"{vb[0]:.1f}..{vb[1]:.1f}", same))
        else:
            same = np.isclose(va, vb, rtol=1e-6, atol=1e-12)
            scalar_rows.append((k, f"{va:.4g}", f"{vb:.4g}", same))
    return scalar_rows, profile_rows, xa


# ------------------------------------------------------------ solver diff
SOLVE_SCALARS = [
    ("T_wall,hot max [K]", lambda d: d.T_wall_hot_K.max()),
    ("x @ T_wall max [mm]", lambda d: d.x_m[d.T_wall_hot_K.idxmax()] * MM),
    ("peak q'' [MW/m2]", lambda d: d.q_w_W_m2.max() / 1e6),
    ("Q_total [kW]", lambda d: d.attrs["Q_total_kW"]),
    ("dp circuit [bar]", lambda d: d.dp_cell_bar.sum()),
    ("outlet T [K]", lambda d: d.attrs["outlet_T_K"]),
    ("outlet p [bar]", lambda d: d.attrs["outlet_p_bar"]),
    ("outlet quality [-]", lambda d: d.quality.iloc[0]
        if d.attrs.get("inlet_at_nozzle", True) else d.quality.iloc[-1]),
    ("max v [m/s]", lambda d: d.v_m_s.max()),
    ("mdot coolant [kg/s]", lambda d: d.attrs["mdot_total"]),
    ("saturation reached", lambda d: d.attrs["saturation_reached"]),
]


def diff_results(ra, rb):
    rows = []
    for label, fn in SOLVE_SCALARS:
        va, vb = fn(ra), fn(rb)
        if isinstance(va, (bool, np.bool_)):
            rows.append((label, str(bool(va)), str(bool(vb)), va == vb))
        else:
            rows.append((label, f"{va:.4g}", f"{vb:.4g}",
                         np.isclose(va, vb, rtol=1e-4)))
    return rows


# ---------------------------------------------------------------- report
def _print_table(title, rows, header):
    changed = [r for r in rows if len(r) < 4 or not r[3]]
    print(f"\n== {title} " + "=" * max(1, 60 - len(title)))
    if not changed:
        print("   (no differences)")
        return
    w0 = max(len(r[0]) for r in changed) + 2
    w1 = max(len(str(r[1])) for r in changed) + 2
    print(f"   {header[0]:<{w0}}{header[1]:<{w1}}{header[2]}")
    for r in changed:
        print(f"   {r[0]:<{w0}}{str(r[1]):<{w1}}{r[2]}")


def figure_diff(la, lb, ra=None, rb=None, name_a="A", name_b="B"):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    solved = ra is not None and rb is not None
    titles = ["Contour & channel envelope", "Helix angle",
              "Width / height / rib", "Flow area"]
    if solved:
        titles += ["Wall & coolant temperature", "Heat flux",
                   "Coolant pressure", "Coolant velocity"]
    rows = 4 if solved else 2
    fig = make_subplots(rows=rows, cols=2, shared_xaxes=True,
                        subplot_titles=titles, vertical_spacing=0.06)

    def pair(r, c, xA, yA, xB, yB, label, color):
        fig.add_trace(go.Scatter(x=xA * MM, y=yA, name=f"{label} {name_a}",
                                 legendgroup=label,
                                 line=dict(color=color)), r, c)
        fig.add_trace(go.Scatter(x=xB * MM, y=yB, name=f"{label} {name_b}",
                                 legendgroup=label, showlegend=False,
                                 line=dict(color=color, dash="dash")), r, c)

    pair(1, 1, la.x, la.r * MM, lb.x, lb.r * MM, "r wall", "#444")
    pair(1, 1, la.x, (la.r + la.t_wall + la.h) * MM,
         lb.x, (lb.r + lb.t_wall + lb.h) * MM, "channel top", "#999")
    pair(1, 2, la.x, np.degrees(la.beta), lb.x, np.degrees(lb.beta),
         "beta [deg]", "#d97706")
    pair(2, 1, la.x, la.w * MM, lb.x, lb.w * MM, "w [mm]", "#2563eb")
    pair(2, 1, la.x, la.h * MM, lb.x, lb.h * MM, "h [mm]", "#16a34a")
    pair(2, 1, la.x, la.t_rib * MM, lb.x, lb.t_rib * MM, "rib [mm]", "#9333ea")
    pair(2, 2, la.x, la.A * 1e6, lb.x, lb.A * 1e6, "A [mm2]", "#0d9488")
    if solved:
        pair(3, 1, ra.x_m.values, ra.T_wall_hot_K, rb.x_m.values,
             rb.T_wall_hot_K, "T_wall hot [K]", "#dc2626")
        pair(3, 1, ra.x_m.values, ra.T_cool_K, rb.x_m.values, rb.T_cool_K,
             "T cool [K]", "#2563eb")
        pair(3, 2, ra.x_m.values, ra.q_w_W_m2 / 1e6, rb.x_m.values,
             rb.q_w_W_m2 / 1e6, "q'' [MW/m2]", "#7c3aed")
        pair(4, 1, ra.x_m.values, ra.p_cool_bar, rb.x_m.values,
             rb.p_cool_bar, "p cool [bar]", "#0d9488")
        pair(4, 2, ra.x_m.values, ra.v_m_s, rb.x_m.values, rb.v_m_s,
             "v [m/s]", "#ea580c")
    fig.update_xaxes(title_text="x [mm]", row=rows)
    fig.update_layout(title=f"regen diff — {name_a} (solid) vs "
                            f"{name_b} (dashed)",
                      template="plotly_white", height=300 * rows + 120)
    return fig


# -------------------------------------------------------------------- CLI
def run_diff(path_a: str, path_b: str, solve: bool = False,
             html: str | None = None):
    ca, cb = RegenConfig.from_yaml(path_a), RegenConfig.from_yaml(path_b)
    name_a, name_b = ca.meta.name, cb.meta.name
    print(f"regen diff: {name_a}  ->  {name_b}")

    _print_table("config", diff_configs(ca, cb),
                 ("key", name_a, name_b))

    la = ChannelLayout(build_contour(ca.contour), ca)
    lb = ChannelLayout(build_contour(cb.contour), cb)
    scalar_rows, profile_rows, _ = diff_layouts(la, lb)
    _print_table("geometry scalars", scalar_rows, ("quantity", name_a, name_b))

    moved = [(f"{lbl} [{unit}]", f"max d {mx:.3g} @ x={xm:.0f} mm",
              f"rms {rms:.3g}", mx < 1e-9)
             for lbl, unit, mx, rms, xm in profile_rows]
    _print_table("geometry profiles (B - A on common grid)", moved,
                 ("profile", "max deviation", "rms"))

    ra = rb = None
    if solve:
        from .solver import RegenSolver
        if not (ca.solver.enabled and cb.solver.enabled):
            print("\n   note: solver disabled in a config; enabling for diff")
        ra, rb = RegenSolver(la, ca).solve(), RegenSolver(lb, cb).solve()
        _print_table("solver", diff_results(ra, rb),
                     ("quantity", name_a, name_b))

    if html:
        os.makedirs(os.path.dirname(html) or ".", exist_ok=True)
        figure_diff(la, lb, ra, rb, name_a, name_b).write_html(
            html, include_plotlyjs=True)
        print(f"\nwrote {html}")
    return la, lb, ra, rb


def main():
    ap = argparse.ArgumentParser(prog="regen_channels.diff")
    ap.add_argument("config_a")
    ap.add_argument("config_b")
    ap.add_argument("--solve", action="store_true",
                    help="run both solvers and diff thermal results")
    ap.add_argument("--html", default=None,
                    help="write Plotly overlay report to this path")
    a = ap.parse_args()
    run_diff(a.config_a, a.config_b, a.solve, a.html)


if __name__ == "__main__":
    main()
