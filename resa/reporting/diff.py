"""Diff two report folders: what inputs changed, and what that did to results.

    python -m resa diff out/E2-C1_aaa out/E2-C1_bbb

Reads config_resolved.yaml (inputs) and results.yaml (outputs) from each
folder and prints two tables. The separation matters: a config diff with an
empty input section but changed results means the CODE changed — worth knowing.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

_SKIP = {"config_hash"}      # always differs, never interesting
_SKIP_PREFIXES = ("uncertainty.low.", "uncertainty.high.")  # band internals: noise


def _flatten(d: dict, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, list):
        return f"<list[{len(v)}]>"
    return str(v)


def diff_dicts(a: dict, b: dict, rtol: float = 1e-9) -> list[tuple]:
    """-> rows (key, val_a, val_b, delta_str) for every differing key."""
    fa, fb = _flatten(a), _flatten(b)
    rows = []
    for k in sorted(set(fa) | set(fb)):
        if k.split(".")[-1] in _SKIP or k.startswith(_SKIP_PREFIXES):
            continue
        va, vb = fa.get(k, "—"), fb.get(k, "—")
        num = (isinstance(va, (int, float)) and isinstance(vb, (int, float))
               and not isinstance(va, bool) and not isinstance(vb, bool))
        if num:
            if math.isclose(va, vb, rel_tol=rtol, abs_tol=1e-12):
                continue
            d = vb - va
            pct = f" ({d / va * 100:+.2f}%)" if va != 0 else ""
            rows.append((k, _fmt(va), _fmt(vb), f"{d:+.6g}{pct}"))
        elif isinstance(va, list) and isinstance(vb, list):
            if va != vb:
                rows.append((k, _fmt(va), _fmt(vb), "list changed"))
        elif va != vb:
            rows.append((k, _fmt(va), _fmt(vb), ""))
    return rows


def _table(rows: list[tuple], headers: tuple) -> str:
    if not rows:
        return "  (no differences)\n"
    widths = [max(len(str(r[i])) for r in rows + [headers]) for i in range(4)]
    fmt = "  {:<%d}  {:>%d}  {:>%d}  {:<%d}" % tuple(widths)
    lines = [fmt.format(*headers), fmt.format(*("-" * w for w in widths))]
    lines += [fmt.format(*r) for r in rows]
    return "\n".join(lines) + "\n"


def _load(folder: Path, name: str) -> dict:
    p = folder / name
    if not p.exists():
        raise FileNotFoundError(f"{p} — is this a resa report folder?")
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def diff_folders(dir_a: str | Path, dir_b: str | Path) -> str:
    a, b = Path(dir_a), Path(dir_b)
    cfg_a, cfg_b = _load(a, "config_resolved.yaml"), _load(b, "config_resolved.yaml")
    res_a, res_b = _load(a, "results.yaml"), _load(b, "results.yaml")

    out = []
    out.append("=== resa diff ===")
    out.append(f"A: {a}  ({res_a.get('engine')}, {res_a.get('mode')})")
    out.append(f"B: {b}  ({res_b.get('engine')}, {res_b.get('mode')})\n")

    out.append("-- INPUT changes (config) --")
    out.append(_table(diff_dicts(cfg_a, cfg_b), ("key", "A", "B", "Δ")))

    warn_a = set(res_a.pop("warnings", []) or [])
    warn_b = set(res_b.pop("warnings", []) or [])

    out.append("-- RESULT changes --")
    out.append(_table(diff_dicts(res_a, res_b), ("key", "A", "B", "Δ")))

    if warn_a != warn_b:
        out.append("-- WARNING changes --")
        for w in sorted(warn_a - warn_b):
            out.append(f"  resolved : {w}")
        for w in sorted(warn_b - warn_a):
            out.append(f"  NEW in B : {w}")
        out.append("")
    return "\n".join(out)
