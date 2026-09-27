// SVG charts: one y-axis per chart (no dual axes), recessive grid, thin
// marks, crosshair + tooltip on hover, legend for >= 2 series.
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { niceTicks, sig, tickLabel } from "../../lib/format";

export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => setW(Math.max(200, Math.floor(e[0].contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export type Scale = ((v: number) => number) & { inv(px: number): number; ticks: number[]; step: number; log: boolean };

export function linear(d0: number, d1: number, r0: number, r1: number, count = 5): Scale {
  const ticks = niceTicks(d0, d1, count);
  const lo = Math.min(d0, ticks[0] ?? d0), hi = Math.max(d1, ticks[ticks.length - 1] ?? d1);
  const f = ((v: number) => r0 + ((v - lo) / (hi - lo || 1)) * (r1 - r0)) as Scale;
  f.inv = (px) => lo + ((px - r0) / (r1 - r0)) * (hi - lo);
  f.ticks = ticks;
  f.step = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
  f.log = false;
  return f;
}

export function logScale(d0: number, d1: number, r0: number, r1: number): Scale {
  const l0 = Math.floor(Math.log10(d0)), l1 = Math.ceil(Math.log10(d1));
  const f = ((v: number) => r0 + ((Math.log10(Math.max(v, 1e-12)) - l0) / (l1 - l0 || 1)) * (r1 - r0)) as Scale;
  f.inv = (px) => Math.pow(10, l0 + ((px - r0) / (r1 - r0)) * (l1 - l0));
  const t: number[] = [];
  for (let e = l0; e <= l1; e++) for (const m of l1 - l0 > 3 ? [1] : [1, 2, 5]) {
    const v = m * Math.pow(10, e);
    if (v >= Math.pow(10, l0) && v <= Math.pow(10, l1)) t.push(v);
  }
  f.ticks = t;
  f.step = 1;
  f.log = true;
  return f;
}

function extent(values: (number | null | undefined)[]): [number, number] {
  let lo = Infinity, hi = -Infinity;
  for (const v of values) if (v !== null && v !== undefined && Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  return lo === Infinity ? [0, 1] : [lo, hi];
}

const fmtTick = (s: Scale) => (v: number) => (s.log ? sig(v, 1) : tickLabel(v, s.step));

// ─── line chart ──────────────────────────────────────────────────────────
export interface Series {
  id: string;
  label: string;
  x: number[];
  y: (number | null)[];
  color: string;
  dash?: boolean;
  width?: number;
  band?: { lo: (number | null)[]; hi: (number | null)[] };
  unit?: string;
  digits?: number;
  hideInLegend?: boolean;
}

export interface RefLine { y: number; label: string; color: string; dash?: boolean }
export interface XMark { x: number; label: string }
export interface Shade { x0: number; x1: number; label?: string; color: string }

export function LineChart({
  series, height = 260, xLabel, yLabel, yDomain, refLines = [], xMarks = [], shades = [], silhouette,
  xFormat, zeroY, legend = true, onHoverX,
}: {
  series: Series[]; height?: number; xLabel: string; yLabel: string; yDomain?: [number | null, number | null];
  refLines?: RefLine[]; xMarks?: XMark[]; shades?: Shade[]; silhouette?: { x: number[]; r: number[] };
  xFormat?(v: number): string; zeroY?: boolean; legend?: boolean; onHoverX?(x: number | null): void;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<{ i: number; px: number; py: number } | null>(null);
  const m = { l: 56, r: 16, t: 14, b: 38 };
  const W = width, H = height;

  const { xs, ys, xAll } = useMemo(() => {
    const xAll = series.flatMap((s) => s.x);
    const [x0, x1] = extent(xAll);
    const yVals = series.flatMap((s) => [...s.y, ...(s.band ? [...s.band.lo, ...s.band.hi] : [])]);
    yVals.push(...refLines.map((r) => r.y));
    let [y0, y1] = extent(yVals);
    if (zeroY) y0 = Math.min(0, y0);
    if (yDomain?.[0] != null) y0 = yDomain[0];
    if (yDomain?.[1] != null) y1 = yDomain[1];
    const pad = (y1 - y0) * 0.06 || 1;
    if (!zeroY || y0 < 0) y0 -= yDomain?.[0] != null ? 0 : pad;
    y1 += yDomain?.[1] != null ? 0 : pad;
    return {
      xs: linear(x0, x1, m.l, W - m.r, Math.max(3, Math.floor(W / 110))),
      ys: linear(y0, y1, H - m.b, m.t, Math.max(3, Math.floor(H / 60))),
      xAll,
    };
  }, [series, refLines, yDomain, W, H, zeroY, m.l, m.r, m.b, m.t]);

  const main = series[0];
  const path = (x: number[], y: (number | null)[]) => {
    let d = "", pen = false;
    for (let i = 0; i < x.length; i++) {
      const v = y[i];
      if (v === null || v === undefined || !Number.isFinite(v)) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${xs(x[i]).toFixed(1)},${ys(v).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  const band = (x: number[], lo: (number | null)[], hi: (number | null)[]) => {
    const pts: string[] = [];
    for (let i = 0; i < x.length; i++) if (hi[i] != null) pts.push(`${xs(x[i]).toFixed(1)},${ys(hi[i] as number).toFixed(1)}`);
    for (let i = x.length - 1; i >= 0; i--) if (lo[i] != null) pts.push(`${xs(x[i]).toFixed(1)},${ys(lo[i] as number).toFixed(1)}`);
    return pts.length ? `M${pts.join("L")}Z` : "";
  };

  const sil = useMemo(() => {
    if (!silhouette) return "";
    const rMax = Math.max(...silhouette.r);
    const h = (H - m.b - m.t) * 0.34;
    const base = H - m.b;
    const pts = silhouette.x.map((x, i) => `${xs(x).toFixed(1)},${(base - (silhouette.r[i] / rMax) * h).toFixed(1)}`);
    return `M${xs(silhouette.x[0])},${base}L${pts.join("L")}L${xs(silhouette.x[silhouette.x.length - 1])},${base}Z`;
  }, [silhouette, xs, H, m.b, m.t]);

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    if (!main || !main.x.length) return;
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    const px = e.clientX - r.left + m.l;
    const xv = xs.inv(px);
    let best = 0, bd = Infinity;
    main.x.forEach((x, i) => { const d = Math.abs(x - xv); if (d < bd) { bd = d; best = i; } });
    setHover({ i: best, px: xs(main.x[best]), py: e.clientY - r.top + m.t });
    onHoverX?.(main.x[best]);
  };

  const valueAt = (s: Series, x: number): number | null => {
    let best = -1, bd = Infinity;
    s.x.forEach((xx, i) => { const d = Math.abs(xx - x); if (d < bd && s.y[i] != null) { bd = d; best = i; } });
    return best >= 0 ? (s.y[best] as number) : null;
  };
  const fx = xFormat ?? fmtTick(xs);
  const shown = series.filter((s) => !s.hideInLegend);

  return (
    <div className="chart" ref={ref}>
      {legend && shown.length > 1 && (
        <div className="legend" style={{ marginBottom: 6 }}>
          {shown.map((s) => (
            <span key={s.id} className="li">
              <span className={`sw${s.dash ? " dash" : ""}`} style={{ background: s.color, color: s.color }} />{s.label}
            </span>
          ))}
          {series.some((s) => s.band) && <span className="li"><span className="sw band" style={{ background: series.find((s) => s.band)!.color }} />uncertainty band</span>}
          {shades.filter((s) => s.label).map((s, i) => <span key={`sh${i}`} className="li"><span className="sw band" style={{ background: s.color }} />{s.label}</span>)}
        </div>
      )}
      <svg width={W} height={H} role="img" aria-label={`${yLabel} versus ${xLabel}`}>
        <g className="grid">
          {ys.ticks.map((t) => <line key={t} x1={m.l} x2={W - m.r} y1={ys(t)} y2={ys(t)} className={t === 0 ? "zero" : ""} />)}
        </g>
        {sil && <path d={sil} fill="var(--ink)" opacity={0.045} />}
        {shades.map((s, i) => (
          <rect key={i} x={xs(s.x0)} width={Math.max(1, xs(s.x1) - xs(s.x0))} y={m.t} height={H - m.b - m.t} fill={s.color} opacity={0.12} />
        ))}
        {xMarks.map((mk) => (
          <g key={mk.label}>
            <line x1={xs(mk.x)} x2={xs(mk.x)} y1={m.t} y2={H - m.b} stroke="var(--ink-4)" strokeDasharray="3 3" />
            <text x={xs(mk.x) + 4} y={m.t + 10} className="tick" style={{ fontSize: 10 }}>{mk.label}</text>
          </g>
        ))}
        {series.map((s) => s.band && <path key={`b${s.id}`} d={band(s.x, s.band.lo, s.band.hi)} fill={s.color} opacity={0.14} />)}
        {refLines.map((r) => (
          <g key={r.label}>
            <line x1={m.l} x2={W - m.r} y1={ys(r.y)} y2={ys(r.y)} stroke={r.color} strokeWidth={1.2} strokeDasharray={r.dash === false ? undefined : "6 4"} />
            <text x={W - m.r - 4} y={ys(r.y) - 5} textAnchor="end" className="tick" style={{ fill: "var(--ink-2)" }}>{r.label}</text>
          </g>
        ))}
        {series.map((s) => (
          <path key={s.id} d={path(s.x, s.y)} fill="none" stroke={s.color} strokeWidth={s.width ?? 2}
            strokeDasharray={s.dash ? "5 4" : undefined} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        <g className="axis">
          <line x1={m.l} x2={W - m.r} y1={H - m.b} y2={H - m.b} stroke="var(--line-2)" />
          {xs.ticks.map((t) => (
            <text key={t} x={xs(t)} y={H - m.b + 15} textAnchor="middle">{fx(t)}</text>
          ))}
          {ys.ticks.map((t) => (
            <text key={t} x={m.l - 8} y={ys(t) + 3.5} textAnchor="end">{fmtTick(ys)(t)}</text>
          ))}
          <text className="axis-label" x={(m.l + W - m.r) / 2} y={H - 4} textAnchor="middle">{xLabel}</text>
          <text className="axis-label" transform={`translate(12 ${(m.t + H - m.b) / 2}) rotate(-90)`} textAnchor="middle">{yLabel}</text>
        </g>
        {hover && main && (
          <g pointerEvents="none">
            <line x1={hover.px} x2={hover.px} y1={m.t} y2={H - m.b} stroke="var(--ink-3)" strokeWidth={1} />
            {series.map((s) => {
              const v = valueAt(s, main.x[hover.i]);
              return v == null ? null : <circle key={s.id} cx={hover.px} cy={ys(v)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />;
            })}
          </g>
        )}
        <rect x={m.l} y={m.t} width={Math.max(0, W - m.l - m.r)} height={Math.max(0, H - m.t - m.b)} fill="transparent"
          onMouseMove={onMove} onMouseLeave={() => { setHover(null); onHoverX?.(null); }} />
      </svg>
      {hover && main && xAll.length > 0 && (
        <div className="chart-tooltip" style={{ left: Math.min(hover.px, W - 190), top: Math.min(Math.max(hover.py, 40), H - 30) }}>
          <div className="tt-x">{xLabel.split(" [")[0]} {fx(main.x[hover.i])}</div>
          {series.map((s) => {
            const v = valueAt(s, main.x[hover.i]);
            return (
              <div key={s.id} className="tt-row">
                <span className="sw" style={{ background: s.color }} />{s.label}
                <span className="tv">{v == null ? "—" : sig(v, s.digits ?? 4)}{s.unit ? ` ${s.unit}` : ""}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── p–h diagram ─────────────────────────────────────────────────────────
export interface PhPath { h: number[]; p: number[]; x: number[]; label: string; color: string }

export function PhChart({ dome, isotherms, path, crit, height = 340 }: {
  dome: { hl: number[]; pl: number[]; hv: number[]; pv: number[] };
  isotherms: { T: number; h: number[]; p: number[] }[];
  path: PhPath;
  crit?: { h: number | null; p: number };
  height?: number;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const H = height;
  const m = { l: 56, r: 18, t: 14, b: 38 };
  const [hover, setHover] = useState<number | null>(null);

  const { xs, ys } = useMemo(() => {
    const [ph0, ph1] = extent(path.h), [pp0, pp1] = extent(path.p);
    const spanH = Math.max(ph1 - ph0, 50);
    const hDome = [...dome.hl, ...dome.hv].filter((h) => Number.isFinite(h));
    let h0 = ph0 - spanH * 0.6, h1 = ph1 + spanH * 0.6;
    // include the dome when it is near the path
    const [d0, d1] = extent(hDome);
    if (d1 > h0 - spanH && d0 < h1 + spanH) { h0 = Math.min(h0, d0 - spanH * 0.1); h1 = Math.max(h1, d1 + spanH * 0.1); }
    const p0 = Math.max(Math.min(pp0 * 0.35, crit ? crit.p * 0.3 : pp0), 1e-3);
    const p1 = Math.max(pp1 * 2.5, crit ? crit.p * 1.3 : pp1);
    return { xs: linear(h0, h1, m.l, W - m.r, Math.max(3, Math.floor(W / 110))), ys: logScale(p0, p1, H - m.b, m.t) };
  }, [path, dome, crit, W, H, m.l, m.r, m.b, m.t]);

  const clipId = useMemo(() => `ph${Math.random().toString(36).slice(2)}`, []);
  const line = (h: number[], p: number[]) => h.map((v, i) => `${i ? "L" : "M"}${xs(v).toFixed(1)},${ys(p[i]).toFixed(1)}`).join("");
  const domePath = dome.hl.length
    ? line([...dome.hl, ...[...dome.hv].reverse()], [...dome.pl, ...[...dome.pv].reverse()])
    : "";
  const n = path.h.length;
  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - r.left + m.l, py = e.clientY - r.top + m.t;
    let best = 0, bd = Infinity;
    for (let i = 0; i < n; i++) {
      const d = (xs(path.h[i]) - px) ** 2 + (ys(path.p[i]) - py) ** 2;
      if (d < bd) { bd = d; best = i; }
    }
    setHover(bd < 60 ** 2 ? best : null);
  };

  return (
    <div className="chart" ref={ref}>
      <div className="legend" style={{ marginBottom: 6 }}>
        <span className="li"><span className="sw" style={{ background: path.color }} />{path.label}</span>
        <span className="li"><span className="sw band" style={{ background: "var(--s4)" }} />two-phase region</span>
        <span className="li"><span className="sw dash" style={{ color: "var(--ink-4)" }} />isotherms</span>
      </div>
      <svg width={W} height={H} role="img" aria-label="Coolant pressure–enthalpy diagram">
        <defs><clipPath id={clipId}><rect x={m.l} y={m.t} width={Math.max(0, W - m.l - m.r)} height={Math.max(0, H - m.t - m.b)} /></clipPath></defs>
        <g className="grid">{ys.ticks.map((t) => <line key={t} x1={m.l} x2={W - m.r} y1={ys(t)} y2={ys(t)} />)}</g>
        <g clipPath={`url(#${clipId})`}>
          {domePath && <path d={domePath} fill="var(--s4)" opacity={0.1} stroke="var(--s4)" strokeWidth={1.2} />}
          {isotherms.map((it) => (
            <g key={it.T}>
              <path d={line(it.h, it.p)} fill="none" stroke="var(--ink-4)" strokeWidth={0.9} strokeDasharray="4 3" />
            </g>
          ))}
          {isotherms.map((it) => {
            // label where the isotherm leaves the top of the plot
            let k = it.p.findIndex((p) => ys(p) < m.t + 16);
            if (k < 0) k = it.p.length - 1;
            const x = xs(it.h[k]);
            if (x < m.l + 4 || x > W - m.r - 30) return null;
            return <text key={`l${it.T}`} x={x + 3} y={Math.max(ys(it.p[k]), m.t + 10)} className="tick" style={{ fontSize: 9.5 }}>{Math.round(it.T)} K</text>;
          })}
          <path d={line(path.h, path.p)} fill="none" stroke={path.color} strokeWidth={2.2} strokeLinejoin="round" />
          {crit?.h != null && <circle cx={xs(crit.h)} cy={ys(crit.p)} r={3.5} fill="var(--s4)" />}
          <circle cx={xs(path.h[0])} cy={ys(path.p[0])} r={5} fill="var(--surface)" stroke={path.color} strokeWidth={2} />
          <circle cx={xs(path.h[n - 1])} cy={ys(path.p[n - 1])} r={5} fill={path.color} stroke="var(--surface)" strokeWidth={2} />
        </g>
        <text x={xs(path.h[0]) + 8} y={ys(path.p[0]) - 8} className="tick" style={{ fill: "var(--ink-2)" }}>inlet</text>
        <text x={xs(path.h[n - 1]) + 8} y={ys(path.p[n - 1]) + 14} className="tick" style={{ fill: "var(--ink-2)" }}>outlet</text>
        {crit?.h != null && <text x={xs(crit.h) - 6} y={ys(crit.p) + 15} textAnchor="end" className="tick">critical point</text>}
        <g className="axis">
          <line x1={m.l} x2={W - m.r} y1={H - m.b} y2={H - m.b} stroke="var(--line-2)" />
          {xs.ticks.map((t) => <text key={t} x={xs(t)} y={H - m.b + 15} textAnchor="middle">{tickLabel(t, xs.step)}</text>)}
          {ys.ticks.map((t) => <text key={t} x={m.l - 8} y={ys(t) + 3.5} textAnchor="end">{sig(t, 2)}</text>)}
          <text className="axis-label" x={(m.l + W - m.r) / 2} y={H - 4} textAnchor="middle">Specific enthalpy [kJ/kg]</text>
          <text className="axis-label" transform={`translate(12 ${(m.t + H - m.b) / 2}) rotate(-90)`} textAnchor="middle">Pressure [bar] (log)</text>
        </g>
        {hover !== null && <circle cx={xs(path.h[hover])} cy={ys(path.p[hover])} r={5} fill="none" stroke="var(--ink)" strokeWidth={1.5} />}
        <rect x={m.l} y={m.t} width={Math.max(0, W - m.l - m.r)} height={Math.max(0, H - m.t - m.b)} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
      </svg>
      {hover !== null && (
        <div className="chart-tooltip" style={{ left: Math.min(xs(path.h[hover]), W - 190), top: ys(path.p[hover]) }}>
          <div className="tt-x">{hover === 0 ? "Inlet" : hover === n - 1 ? "Outlet" : `Station at x = ${sig(path.x[Math.min(hover, path.x.length - 1)] * 1e3, 3)} mm`}</div>
          <div className="tt-row">Enthalpy<span className="tv">{sig(path.h[hover], 4)} kJ/kg</span></div>
          <div className="tt-row">Pressure<span className="tv">{sig(path.p[hover], 4)} bar</span></div>
        </div>
      )}
    </div>
  );
}

// ─── heatmap (operating envelope) ────────────────────────────────────────
export function Heatmap({ x, y, z, mask, xLabel, yLabel, zLabel, zUnit, height = 300, marker }: {
  x: number[]; y: number[]; z: number[][]; mask?: boolean[][]; xLabel: string; yLabel: string; zLabel: string; zUnit: string;
  height?: number; marker?: { x: number; y: number };
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const H = height;
  const m = { l: 56, r: 90, t: 12, b: 38 };
  const [hover, setHover] = useState<{ i: number; j: number } | null>(null);
  const xs = linear(x[0], x[x.length - 1], m.l, W - m.r);
  const ys = linear(y[0], y[y.length - 1], H - m.b, m.t);
  const [z0, z1] = extent(z.flat());
  const cw = (W - m.l - m.r) / x.length, ch = (H - m.t - m.b) / y.length;
  // sequential single hue (hot) light -> dark
  const color = (v: number) => `color-mix(in oklab, var(--hot) ${Math.round(12 + 88 * ((v - z0) / (z1 - z0 || 1)))}%, var(--surface))`;
  const X = (i: number) => m.l + i * cw, Y = (j: number) => H - m.b - (j + 1) * ch;
  return (
    <div className="chart" ref={ref}>
      <svg width={W} height={H} role="img" aria-label={`${zLabel} over ${xLabel} and ${yLabel}`}>
        {z.map((row, j) => row.map((v, i) => (
          <rect key={`${i}-${j}`} x={X(i)} y={Y(j)} width={cw + 0.5} height={ch + 0.5} fill={Number.isFinite(v) ? color(v) : "var(--surface-3)"}
            onMouseEnter={() => setHover({ i, j })} />
        )))}
        {mask && z.map((row, j) => row.map((_v, i) => mask[j]?.[i] ? (
          <path key={`m${i}-${j}`} d={`M${X(i)},${Y(j) + ch}L${X(i) + cw},${Y(j)}`} stroke="var(--ink)" strokeWidth={0.8} opacity={0.5} />
        ) : null))}
        {marker && <circle cx={xs(marker.x)} cy={ys(marker.y)} r={5} fill="none" stroke="var(--ink)" strokeWidth={2} />}
        <g className="axis">
          {xs.ticks.map((t) => <text key={t} x={xs(t)} y={H - m.b + 15} textAnchor="middle">{tickLabel(t, xs.step)}</text>)}
          {ys.ticks.map((t) => <text key={t} x={m.l - 8} y={ys(t) + 3.5} textAnchor="end">{tickLabel(t, ys.step)}</text>)}
          <text className="axis-label" x={(m.l + W - m.r) / 2} y={H - 4} textAnchor="middle">{xLabel}</text>
          <text className="axis-label" transform={`translate(12 ${(m.t + H - m.b) / 2}) rotate(-90)`} textAnchor="middle">{yLabel}</text>
        </g>
        <g transform={`translate(${W - m.r + 18} ${m.t})`}>
          {Array.from({ length: 40 }, (_, k) => (
            <rect key={k} x={0} y={(H - m.t - m.b) * (1 - (k + 1) / 40)} width={12} height={(H - m.t - m.b) / 40 + 0.5} fill={color(z0 + ((k + 0.5) / 40) * (z1 - z0))} />
          ))}
          <text className="tick" x={16} y={8}>{sig(z1, 3)}</text>
          <text className="tick" x={16} y={H - m.t - m.b}>{sig(z0, 3)}</text>
          <text className="tick" x={16} y={(H - m.t - m.b) / 2}>{zUnit}</text>
        </g>
        <rect x={m.l} y={m.t} width={W - m.l - m.r} height={H - m.t - m.b} fill="transparent" onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const i = Math.floor((e.clientX - r.left) / cw), j = Math.floor((r.bottom - e.clientY) / ch);
            if (i >= 0 && i < x.length && j >= 0 && j < y.length) setHover({ i, j });
          }} />
      </svg>
      {hover && (
        <div className="chart-tooltip" style={{ left: Math.min(X(hover.i), W - 200), top: Y(hover.j) }}>
          <div className="tt-x">{xLabel.split(" [")[0]} {sig(x[hover.i], 3)} · {yLabel.split(" [")[0]} {sig(y[hover.j], 3)}</div>
          <div className="tt-row">{zLabel}<span className="tv">{sig(z[hover.j][hover.i], 4)} {zUnit}</span></div>
          {mask?.[hover.j]?.[hover.i] && <div className="tt-row" style={{ color: "var(--bad)" }}>flow separation risk</div>}
        </div>
      )}
    </div>
  );
}

export function ChartCard({ title, sub, children, actions }: { title: ReactNode; sub?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      <div className="card-head"><h3>{title}</h3>{sub && <span className="sub">{sub}</span>}<span className="spacer" />{actions}</div>
      <div className="card-body">{children}</div>
    </section>
  );
}
