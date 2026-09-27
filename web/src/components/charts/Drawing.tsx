// The engine as a technical drawing: true-scale meridian contour, mirrored,
// with a dash-dot centerline and dimension lines. Optional heat-flux tint
// on the wall (hot accent intensity ∝ q).
import { useMemo } from "react";
import { sig } from "../../lib/format";
import { useWidth } from "./Chart";

export interface DrawingDims {
  chamber_d: number; throat_d: number; exit_d: number; chamber_len: number; nozzle_len: number;
}

export function EngineDrawing({ x, r, dims, heat, height = 300, animate = true, channelSpan, compact }: {
  x: number[]; r: number[]; dims?: DrawingDims; heat?: { x: number[]; q: number[] } | null; height?: number;
  animate?: boolean; channelSpan?: [number, number] | null; compact?: boolean;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const H = height;
  const g = useMemo(() => {
    if (!x.length) return null;
    const x0 = Math.min(...x), x1 = Math.max(...x), rMax = Math.max(...r);
    const padL = compact ? 8 : 96, padR = compact ? 8 : 96, padT = compact ? 8 : 40, padB = compact ? 8 : 52;
    const s = Math.min((W - padL - padR) / (x1 - x0), (H - padT - padB) / (2 * rMax));
    const cx = padL + ((W - padL - padR) - (x1 - x0) * s) / 2;
    const cy = padT + (H - padT - padB) / 2;
    const X = (v: number) => cx + (v - x0) * s;
    const Yu = (v: number) => cy - v * s;
    const Yl = (v: number) => cy + v * s;
    const upper = x.map((v, i) => `${i ? "L" : "M"}${X(v).toFixed(2)},${Yu(r[i]).toFixed(2)}`).join("");
    const lower = x.map((v, i) => `${i ? "L" : "M"}${X(v).toFixed(2)},${Yl(r[i]).toFixed(2)}`).join("");
    const it = r.indexOf(Math.min(...r));
    return { x0, x1, rMax, s, X, Yu, Yl, cy, upper, lower, it, padB, len: (x1 - x0) * s * 1.6 + 4 * rMax * s };
  }, [x, r, W, H, compact]);

  const heatSegs = useMemo(() => {
    if (!g || !heat || !heat.q.length) return null;
    const qMax = Math.max(...heat.q.filter(Number.isFinite));
    const segs: { d: string; t: number }[] = [];
    for (let i = 1; i < heat.x.length; i++) {
      const ri = interp(x, r, heat.x[i]), rj = interp(x, r, heat.x[i - 1]);
      const t = ((heat.q[i] + heat.q[i - 1]) / 2) / (qMax || 1);
      segs.push({ d: `M${g.X(heat.x[i - 1])},${g.Yu(rj)}L${g.X(heat.x[i])},${g.Yu(ri)}M${g.X(heat.x[i - 1])},${g.Yl(rj)}L${g.X(heat.x[i])},${g.Yl(ri)}`, t });
    }
    return segs;
  }, [g, heat, x, r]);

  if (!g) return <div ref={ref} style={{ height: H }} />;
  const { X, Yu, Yl, cy } = g;
  const xt = x[g.it], rt = r[g.it];
  const xe = g.x1, re = r[r.length - 1], xs0 = g.x0, rc = r[0];
  const dimY = cy + g.rMax * g.s + 26;

  return (
    <div className="drawing" ref={ref}>
      <svg width={W} height={H} role="img" aria-label="Engine contour drawing">
        <defs>
          <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink-4)" strokeWidth="0.8" />
          </pattern>
        </defs>
        {/* gas volume tint */}
        <path d={`${g.upper}L${X(xe)},${Yl(re)}${x.map((_v, i) => `L${X(x[x.length - 1 - i])},${Yl(r[r.length - 1 - i])}`).join("")}Z`}
          fill="var(--hot)" opacity={0.035} />
        {channelSpan && (
          <>
            <rect x={X(channelSpan[0])} y={Yu(g.rMax) - 10} width={X(channelSpan[1]) - X(channelSpan[0])} height={4} fill="var(--cool)" opacity={0.7} rx={2} />
            <rect x={X(channelSpan[0])} y={Yl(g.rMax) + 6} width={X(channelSpan[1]) - X(channelSpan[0])} height={4} fill="var(--cool)" opacity={0.7} rx={2} />
          </>
        )}
        <line className="center" x1={X(xs0) - 18} x2={X(xe) + 18} y1={cy} y2={cy} />
        {/* injector face */}
        <line className="ink" x1={X(xs0)} x2={X(xs0)} y1={Yu(rc)} y2={Yl(rc)} strokeWidth={1.2} opacity={0.6} />
        <path d={g.upper} className="ink" fill="none" strokeWidth={1.8} strokeLinejoin="round"
          style={animate ? { strokeDasharray: g.len, strokeDashoffset: 0, animation: "draw 1.1s ease-out", ["--len" as string]: g.len } : undefined} />
        <path d={g.lower} className="ink" fill="none" strokeWidth={1.8} strokeLinejoin="round"
          style={animate ? { strokeDasharray: g.len, strokeDashoffset: 0, animation: "draw 1.1s ease-out", ["--len" as string]: g.len } : undefined} />
        {heatSegs?.map((sg, i) => (
          <path key={i} d={sg.d} stroke="var(--hot)" strokeWidth={4.5} strokeLinecap="round" opacity={0.12 + 0.88 * Math.pow(sg.t, 1.3)} />
        ))}
        {!compact && dims && (
          <g>
            {/* diameters */}
            <DimV x={X(xs0) - 26} y0={Yu(rc)} y1={Yl(rc)} label={`Ø ${sig(dims.chamber_d * 1e3, 3)}`} side="left" />
            <DimV x={X(xt)} y0={Yu(rt)} y1={Yl(rt)} label={`Ø ${sig(dims.throat_d * 1e3, 3)}`} side="inner" />
            <DimV x={X(xe) + 26} y0={Yu(re)} y1={Yl(re)} label={`Ø ${sig(dims.exit_d * 1e3, 3)}`} side="right" />
            {/* lengths */}
            <DimH y={dimY} x0={X(xs0)} x1={X(xt)} label={`${sig(dims.chamber_len * 1e3, 3)}`} />
            <DimH y={dimY} x0={X(xt)} x1={X(xe)} label={`${sig(dims.nozzle_len * 1e3, 3)}`} />
            <line className="dim" x1={X(xs0)} x2={X(xs0)} y1={Yl(rc) + 4} y2={dimY + 5} />
            <line className="dim" x1={X(xt)} x2={X(xt)} y1={Yl(rt) + 4} y2={dimY + 5} />
            <line className="dim" x1={X(xe)} x2={X(xe)} y1={Yl(re) + 4} y2={dimY + 5} />
            <text className="dim-text" x={W - 8} y={H - 6} textAnchor="end" style={{ fill: "var(--ink-3)" }}>all dimensions in mm · true scale</text>
          </g>
        )}
      </svg>
    </div>
  );
}

function interp(xa: number[], ya: number[], v: number): number {
  if (v <= xa[0]) return ya[0];
  for (let i = 1; i < xa.length; i++) if (v <= xa[i]) {
    const t = (v - xa[i - 1]) / (xa[i] - xa[i - 1] || 1);
    return ya[i - 1] + t * (ya[i] - ya[i - 1]);
  }
  return ya[ya.length - 1];
}

function Arrow({ x, y, dir }: { x: number; y: number; dir: "up" | "down" | "left" | "right" }) {
  const d = { up: `M${x},${y}l-3,6h6z`, down: `M${x},${y}l-3,-6h6z`, left: `M${x},${y}l6,-3v6z`, right: `M${x},${y}l-6,-3v6z` }[dir];
  return <path d={d} fill="var(--ink-3)" />;
}

function DimV({ x, y0, y1, label, side }: { x: number; y0: number; y1: number; label: string; side: "left" | "right" | "inner" }) {
  const mid = (y0 + y1) / 2;
  const tx = side === "left" ? x - 6 : side === "right" ? x + 6 : x + 5;
  const anchor = side === "left" ? "end" : "start";
  return (
    <g>
      <line className="dim" x1={x} x2={x} y1={y0} y2={y1} />
      <Arrow x={x} y={y0} dir="up" /><Arrow x={x} y={y1} dir="down" />
      {side !== "inner" && <>
        <line className="dim" x1={side === "left" ? x - 4 : x + 4} x2={side === "left" ? x + 26 : x - 26} y1={y0} y2={y0} opacity={0.5} />
        <line className="dim" x1={side === "left" ? x - 4 : x + 4} x2={side === "left" ? x + 26 : x - 26} y1={y1} y2={y1} opacity={0.5} />
      </>}
      {side === "inner" && <line className="dim" x1={x} x2={x} y1={y0 - 4} y2={y0 - 16} />}
      <text className="dim-text" x={tx} y={side === "inner" ? y0 - 20 : mid + 3.5} textAnchor={side === "inner" ? "middle" : anchor}>{label}</text>
    </g>
  );
}

function DimH({ y, x0, x1, label }: { y: number; x0: number; x1: number; label: string }) {
  if (x1 - x0 < 4) return null;
  return (
    <g>
      <line className="dim" x1={x0} x2={x1} y1={y} y2={y} />
      <Arrow x={x0} y={y} dir="left" /><Arrow x={x1} y={y} dir="right" />
      <text className="dim-text" x={(x0 + x1) / 2} y={y - 5} textAnchor="middle">{label}</text>
    </g>
  );
}
