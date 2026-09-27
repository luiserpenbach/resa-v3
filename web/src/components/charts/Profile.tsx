// Channel-dimension profiles: constant, or varying along the engine axis
// (stations [[x_m, value], ...]); edited on a mini chart with draggable
// points plus a table.
import { useRef, useState } from "react";
import { sig } from "../../lib/format";
import { NumberInput, Segmented } from "../ui/controls";
import { Icon } from "../ui/icons";
import { linear, useWidth } from "./Chart";

export type ProfileValue = number | number[][] | { points: number[][]; interp?: string };

export function ProfileInput({ value, onChange, unit, scale, xRange, silhouette, label }: {
  value: ProfileValue; onChange(v: ProfileValue): void; unit: string; scale: number;
  xRange: [number, number]; silhouette?: { x: number[]; r: number[] }; label: string;
}) {
  const points = Array.isArray(value) ? value : typeof value === "object" ? value.points : null;
  const constant = typeof value === "number" ? value : null;
  const toVarying = () => {
    const v = constant ?? 0;
    const [x0, x1] = xRange;
    const xs = [x0, x0 * 0.35, 0, x1 * 0.4, x1];
    onChange(xs.map((x) => [Number(x.toFixed(4)), v]));
  };
  const toConstant = () => {
    const pts = points ?? [];
    const mid = pts.length ? pts.reduce((a, p) => (Math.abs(p[0]) < Math.abs(a[0]) ? p : a))[1] : 0;
    onChange(mid);
  };
  return (
    <div className="stack-sm">
      <div className="row">
        <span className="field-label" style={{ flex: 1 }}>{label}</span>
        <Segmented value={points ? "vary" : "const"} onChange={(v) => (v === "vary" ? toVarying() : toConstant())}
          options={[{ value: "const", label: "Constant" }, { value: "vary", label: "Varies" }]} />
      </div>
      {constant !== null ? (
        <NumberInput value={constant} unit={unit} scale={scale} onChange={(v) => v !== null && onChange(v)} />
      ) : points ? (
        <ProfileEditor points={points} onChange={onChange} unit={unit} scale={scale} xRange={xRange} silhouette={silhouette} />
      ) : null}
    </div>
  );
}

function ProfileEditor({ points, onChange, unit, scale, xRange, silhouette }: {
  points: number[][]; onChange(v: number[][]): void; unit: string; scale: number; xRange: [number, number];
  silhouette?: { x: number[]; r: number[] };
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const H = 120;
  const m = { l: 40, r: 10, t: 10, b: 20 };
  const vals = points.map((p) => p[1] * scale);
  const vMax = Math.max(...vals, 1e-9) * 1.3;
  const pad = (xRange[1] - xRange[0]) * 1e3 * 0.04;   // keep end points off the axis labels
  const xs = linear(xRange[0] * 1e3 - pad, xRange[1] * 1e3 + pad, m.l, W - m.r, 4);
  const ys = linear(0, vMax, H - m.b, m.t, 3);
  const drag = useRef<number | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const sorted = [...points].sort((a, b) => a[0] - b[0]);

  const set = (i: number, x: number, v: number) => {
    const next = points.map((p, k) => (k === i ? [Number(x.toFixed(4)), Number(v.toPrecision(4))] : p));
    onChange(next.sort((a, b) => a[0] - b[0]));
  };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (drag.current === null) return;
    const r = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const x = Math.min(Math.max(xs.inv(px), xRange[0] * 1e3), xRange[1] * 1e3) / 1e3;
    const v = Math.max(ys.inv(py), 0.001) / scale;
    const i = drag.current;
    const next = points.map((p, k) => (k === i ? [Number(x.toFixed(4)), Number((Math.round(v * scale * 100) / 100 / scale).toPrecision(4))] : p));
    onChange(next);
  };
  const path = sorted.map((p, i) => `${i ? "L" : "M"}${xs(p[0] * 1e3)},${ys(p[1] * scale)}`).join("");
  const rMax = silhouette ? Math.max(...silhouette.r) : 1;
  const sil = silhouette ? `M${xs(silhouette.x[0] * 1e3)},${H - m.b}` + silhouette.x.map((x, i) => `L${xs(x * 1e3)},${H - m.b - (silhouette.r[i] / rMax) * (H - m.b - m.t) * 0.5}`).join("") + `L${xs(silhouette.x[silhouette.x.length - 1] * 1e3)},${H - m.b}Z` : "";

  return (
    <div className="profile-editor">
      <div className="chart" ref={ref}>
        <svg width={W} height={H} onPointerMove={onMove} onPointerUp={() => (drag.current = null)} onPointerLeave={() => (drag.current = null)}
          style={{ touchAction: "none", background: "var(--surface-2)", borderRadius: 6 }}>
          {sil && <path d={sil} fill="var(--ink)" opacity={0.05} />}
          {ys.ticks.map((t) => <g key={t}><line x1={m.l} x2={W - m.r} y1={ys(t)} y2={ys(t)} stroke="var(--line)" />
            <text x={m.l - 5} y={ys(t) + 3} textAnchor="end" className="tick">{sig(t, 2)}</text></g>)}
          {xs.ticks.map((t) => <text key={t} x={xs(t)} y={H - 5} textAnchor="middle" className="tick">{t}</text>)}
          <line x1={xs(0)} x2={xs(0)} y1={m.t} y2={H - m.b} stroke="var(--ink-4)" strokeDasharray="3 3" />
          <path d={path} fill="none" stroke="var(--cool)" strokeWidth={2} />
          {points.map((p, i) => (
            <circle key={i} cx={xs(p[0] * 1e3)} cy={ys(p[1] * scale)} r={sel === i ? 6 : 5} fill="var(--surface)" stroke="var(--cool)" strokeWidth={2}
              style={{ cursor: "grab" }} onPointerDown={(e) => { (e.target as Element).setPointerCapture?.(e.pointerId); drag.current = i; setSel(i); }} />
          ))}
        </svg>
      </div>
      <table className="profile-table">
        <thead><tr><td className="muted" style={{ fontSize: 11 }}>x [mm]</td><td className="muted" style={{ fontSize: 11 }}>value [{unit}]</td><td /></tr></thead>
        <tbody>
          {points.map((p, i) => (
            <tr key={i} onFocus={() => setSel(i)}>
              <td><NumberInputCell value={p[0] * 1e3} onChange={(v) => set(i, v / 1e3, p[1])} /></td>
              <td><NumberInputCell value={p[1] * scale} onChange={(v) => set(i, p[0], v / scale)} /></td>
              <td style={{ width: 28 }}>
                <button className="btn btn-ghost btn-sm btn-icon" disabled={points.length <= 2} aria-label="Remove station"
                  onClick={() => onChange(points.filter((_, k) => k !== i))}><Icon name="close" size="sm" /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn btn-sm" onClick={() => {
        // insert midway into the widest gap
        let gap = 0, at = 0;
        for (let i = 1; i < sorted.length; i++) if (sorted[i][0] - sorted[i - 1][0] > gap) { gap = sorted[i][0] - sorted[i - 1][0]; at = i; }
        const a = sorted[at - 1] ?? sorted[0], b = sorted[at] ?? sorted[0];
        onChange([...points, [Number(((a[0] + b[0]) / 2).toFixed(4)), (a[1] + b[1]) / 2]].sort((p, q) => p[0] - q[0]));
      }}><Icon name="plus" size="sm" />Add station</button>
    </div>
  );
}

function NumberInputCell({ value, onChange }: { value: number; onChange(v: number): void }) {
  const [t, setT] = useState<string | null>(null);
  return (
    <input value={t ?? String(Number(value.toPrecision(5)))} onFocus={() => setT(String(Number(value.toPrecision(5))))}
      onChange={(e) => { setT(e.target.value); const n = Number(e.target.value); if (e.target.value.trim() !== "" && Number.isFinite(n)) onChange(n); }}
      onBlur={() => setT(null)} />
  );
}

// ─── cross-section through the wall at one station ───────────────────────
export function CrossSection({ r, t, h, w, rib, n, closeout }: { r: number; t: number; h: number; w: number; rib: number; n: number; closeout: number }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const H = 230;
  // show ~3.5 pitches around the top of the ring, true scale
  const pitchAng = (2 * Math.PI) / n;
  const span = Math.min(pitchAng * 3.4, Math.PI * 0.9);
  const rOut = r + t + h + closeout;
  const chord = 2 * rOut * Math.sin(span / 2);
  const depth = rOut - r * Math.cos(span / 2);
  const s = Math.min((W - 40) / chord, (H - 60) / depth);
  const cx = W / 2, cy = 30 + rOut * s;
  const P = (rad: number, a: number) => `${(cx + rad * s * Math.sin(a)).toFixed(2)},${(cy - rad * s * Math.cos(a)).toFixed(2)}`;
  const arc = (rad: number, a0: number, a1: number, move = true) => {
    const steps = 40;
    let d = "";
    for (let i = 0; i <= steps; i++) { const a = a0 + ((a1 - a0) * i) / steps; d += `${i === 0 && move ? "M" : "L"}${P(rad, a)}`; }
    return d;
  };
  const a0 = -span / 2, a1 = span / 2;
  const metal = `${arc(r, a0, a1)}${arc(rOut, a1, a0, false)}Z`;
  const rm = r + t + h / 2;
  const half = w / 2 / rm;
  const kMax = Math.ceil(span / pitchAng) + 1;
  const channels: string[] = [];
  for (let k = -kMax; k <= kMax; k++) {
    const ac = k * pitchAng;
    const b0 = Math.max(ac - half, a0), b1 = Math.min(ac + half, a1);
    if (b1 <= b0) continue;
    channels.push(`${arc(r + t, b0, b1)}${arc(r + t + h, b1, b0, false)}Z`);
  }
  return (
    <div className="drawing" ref={ref}>
      <svg width={W} height={H} role="img" aria-label={`Wall cross-section: ${n} channels, rib ${sig(rib * 1e3, 3)} mm, hot wall ${sig(t * 1e3, 3)} mm`}>
        <defs>
          <pattern id="metal" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="5" height="5" fill="var(--surface-3)" />
            <line x1="0" y1="0" x2="0" y2="5" stroke="var(--ink-4)" strokeWidth="0.7" />
          </pattern>
        </defs>
        <path d={metal} fill="url(#metal)" stroke="var(--ink)" strokeWidth={1.2} />
        {channels.map((d, i) => <path key={i} d={d} fill="var(--cool)" fillOpacity={0.28} stroke="var(--cool)" strokeWidth={1.2} />)}
        <path d={arc(r, a0, a1)} fill="none" stroke="var(--hot)" strokeWidth={3} />
        <text className="dim-text" x={cx} y={cy - r * s + 16} textAnchor="middle" style={{ fill: "var(--hot)" }}>hot gas side</text>
        <text className="dim-text" x={cx} y={H - 8} textAnchor="middle" style={{ fill: "var(--ink-3)" }}>
          {sig(w * 1e3, 3)} × {sig(h * 1e3, 3)} mm channels · true scale
        </text>
      </svg>
    </div>
  );
}
