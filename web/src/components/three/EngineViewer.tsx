// 3D view of a regeneratively cooled thrust chamber: hot-gas wall of
// revolution, milled cooling channels (coolant bodies instanced N times about
// the x axis) and the closeout jacket, with an angular cutaway that shows the
// wall in section. Drafting-table look: matte materials, thin ink lines,
// hatched section faces. All colours come from the app's CSS custom
// properties and are re-read when <html data-theme> changes.
import { useEffect, useMemo, useRef, useState } from "react";
import type { JSX } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

// ─── public API ──────────────────────────────────────────────────────────
export interface AssemblyData {
  n_channels: number;
  n_stations: number;
  helical: boolean;
  closeout_thickness_m: number;
  profile: { x_m: number[]; r_inner_m: number[]; r_floor_m: number[]; r_top_m: number[]; r_outer_m: number[] };
  channel: { floor_L: number[][]; floor_R: number[][]; top_L: number[][]; top_R: number[][] };
}

export interface EngineViewerProps {
  assembly?: AssemblyData | null;
  contour?: { x_m: number[]; r_m: number[] } | null;
  heat?: { x_m: number[]; value: number[] } | null;
  height?: number;
}

type CutMode = "full" | "quarter" | "half";
interface ViewOpts { cut: CutMode; closeout: boolean; channels: boolean }

// ─── normalised model description (metres, axis = +x) ────────────────────
type P3 = [number, number, number];

interface ChannelSpec {
  N: number;
  alpha: number;               // angular pitch 2π/N
  fL: P3[]; fR: P3[]; tL: P3[]; tR: P3[];   // channel 0 corners per station (L on the +θ side)
  thetaC: Float64Array;        // channel 0 centre angle per station (mid height)
  halfW: Float64Array;         // channel 0 angular half width per station (mid height)
  thetaMid: number;            // centre angle at the middle station (cut snapping)
  nFloor: number;              // arc subdivisions across a channel
  nLand: number;               // arc subdivisions across a land
}

interface Spec {
  n: number;
  x: Float64Array; rIn: Float64Array; rFloor: Float64Array; rTop: Float64Array; rOut: Float64Array;
  channels: ChannelSpec | null;
  hasCloseout: boolean;
  xMin: number; xMax: number; rMax: number;
  hatch: number;               // section hatch pitch, metres
}

const TAU = Math.PI * 2;
const REV_SEGS = 192;
const CAM_DIR = new THREE.Vector3(0.62, 0.36, 0.7).normalize();   // nozzle-exit side, 3/4, slightly above
const PHI_CAM = Math.atan2(CAM_DIR.z, CAM_DIR.y);                  // θ = atan2(z, y) of the camera side

const wrapPi = (a: number): number => a - TAU * Math.floor((a + Math.PI) / TAU);
const ang = (p: P3): number => Math.atan2(p[2], p[1]);
const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function p3(v: unknown): P3 | null {
  if (!Array.isArray(v) || v.length < 3 || !fin(v[0]) || !fin(v[1]) || !fin(v[2])) return null;
  return [v[0], v[1], v[2]];
}

function rotX(p: P3, a: number): P3 {
  const c = Math.cos(a), s = Math.sin(a);
  return [p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c];
}

/** Point on the circular arc (about x) from a to b, parameter t ∈ [0, 1]. */
function arc(a: P3, b: P3, t: number, out: P3): void {
  const ta = ang(a), dt = wrapPi(ang(b) - ta);
  const ra = Math.hypot(a[1], a[2]), rb = Math.hypot(b[1], b[2]);
  const th = ta + dt * t, r = ra + (rb - ra) * t;
  out[0] = a[0] + (b[0] - a[0]) * t;
  out[1] = r * Math.cos(th);
  out[2] = r * Math.sin(th);
}

function finishSpec(x: number[], rIn: number[], rFloor: number[], rTop: number[], rOut: number[],
  channels: ChannelSpec | null, hasCloseout: boolean, hatchRef: number): Spec {
  const n = x.length;
  let rMax = 0;
  for (const r of rOut) rMax = Math.max(rMax, r);
  return {
    n, channels, hasCloseout,
    x: Float64Array.from(x), rIn: Float64Array.from(rIn), rFloor: Float64Array.from(rFloor),
    rTop: Float64Array.from(rTop), rOut: Float64Array.from(rOut),
    xMin: x[0], xMax: x[n - 1], rMax,
    hatch: hatchRef > 0 ? hatchRef : Math.max(rMax, 1e-6) * 0.004,
  };
}

function specFromAssembly(a: AssemblyData): Spec | null {
  const p = a.profile;
  if (!p) return null;
  const n0 = Math.min(p.x_m?.length ?? 0, p.r_inner_m?.length ?? 0, p.r_floor_m?.length ?? 0,
    p.r_top_m?.length ?? 0, p.r_outer_m?.length ?? 0);
  const N = Math.floor(a.n_channels);
  const c = a.channel;
  let chOk = N >= 1 && !!c && [c.floor_L, c.floor_R, c.top_L, c.top_R].every((arr) => Array.isArray(arr) && arr.length >= n0);

  const keep: number[] = [];
  for (let i = 0; i < n0; i++) {
    if (fin(p.x_m[i]) && fin(p.r_inner_m[i]) && fin(p.r_floor_m[i]) && fin(p.r_top_m[i]) && fin(p.r_outer_m[i])) keep.push(i);
  }
  if (keep.length < 2) return null;
  if (p.x_m[keep[0]] > p.x_m[keep[keep.length - 1]]) keep.reverse();

  const x: number[] = [], rIn: number[] = [], rFl: number[] = [], rTp: number[] = [], rOu: number[] = [];
  const fL: P3[] = [], fR: P3[] = [], tL: P3[] = [], tR: P3[] = [];
  for (const i of keep) {
    const ri = Math.max(0, p.r_inner_m[i]);
    const rf = Math.max(ri, p.r_floor_m[i]);
    const rt = Math.max(rf, p.r_top_m[i]);
    const ro = Math.max(rt, p.r_outer_m[i]);
    x.push(p.x_m[i]); rIn.push(ri); rFl.push(rf); rTp.push(rt); rOu.push(ro);
    if (chOk) {
      const q = [p3(c.floor_L[i]), p3(c.floor_R[i]), p3(c.top_L[i]), p3(c.top_R[i])];
      if (q.some((v) => v === null)) chOk = false;
      else { fL.push(q[0]!); fR.push(q[1]!); tL.push(q[2]!); tR.push(q[3]!); }
    }
  }
  const n = x.length;
  const hasCloseout = rOu.some((r, i) => r - rTp[i] > 1e-9);

  let channels: ChannelSpec | null = null;
  if (chOk && n >= 2) {
    const mid = n >> 1;
    let L = { f: fL, t: tL }, R = { f: fR, t: tR };
    if (wrapPi(ang(fL[mid]) - ang(fR[mid])) < 0) [L, R] = [R, L];   // make L the +θ side
    const alpha = TAU / N;
    const thetaC = new Float64Array(n), halfW = new Float64Array(n);
    let maxFloor = 0, maxLand = 0;
    for (let i = 0; i < n; i++) {
      const mL: P3 = [0, (L.f[i][1] + L.t[i][1]) / 2, (L.f[i][2] + L.t[i][2]) / 2];
      const mR: P3 = [0, (R.f[i][1] + R.t[i][1]) / 2, (R.f[i][2] + R.t[i][2]) / 2];
      const d = wrapPi(ang(mL) - ang(mR));
      thetaC[i] = ang(mR) + d / 2;
      halfW[i] = Math.abs(d) / 2;
      const floorAng = Math.abs(wrapPi(ang(L.f[i]) - ang(R.f[i])));
      const topAng = Math.abs(wrapPi(ang(L.t[i]) - ang(R.t[i])));
      maxFloor = Math.max(maxFloor, floorAng, topAng);
      maxLand = Math.max(maxLand, alpha - Math.min(floorAng, topAng));
    }
    const step = TAU / 200;
    channels = {
      N, alpha, fL: L.f, fR: R.f, tL: L.t, tR: R.t, thetaC, halfW, thetaMid: thetaC[mid],
      nFloor: Math.min(8, Math.max(1, Math.ceil(maxFloor / step))),
      nLand: Math.min(24, Math.max(1, Math.ceil(maxLand / step))),
    };
  }

  let minThk = Infinity;
  for (let i = 0; i < n; i++) {
    for (const t of [rFl[i] - rIn[i], channels ? rTp[i] - rFl[i] : rTp[i] - rIn[i], hasCloseout ? rOu[i] - rTp[i] : Infinity]) {
      if (t > 1e-9) minThk = Math.min(minThk, t);
    }
  }
  return finishSpec(x, rIn, rFl, rTp, rOu, channels, hasCloseout, Number.isFinite(minThk) ? minThk * 0.42 : 0);
}

function specFromContour(ct: { x_m: number[]; r_m: number[] }): Spec | null {
  const n0 = Math.min(ct.x_m?.length ?? 0, ct.r_m?.length ?? 0);
  const keep: number[] = [];
  for (let i = 0; i < n0; i++) if (fin(ct.x_m[i]) && fin(ct.r_m[i])) keep.push(i);
  if (keep.length < 2) return null;
  if (ct.x_m[keep[0]] > ct.x_m[keep[keep.length - 1]]) keep.reverse();
  const x = keep.map((i) => ct.x_m[i]);
  const r = keep.map((i) => Math.max(0, ct.r_m[i]));
  const t = Math.max(...r) * 0.02 || 1e-4;
  const ro = r.map((v) => v + t);
  return finishSpec(x, r, ro, ro, ro, null, false, t * 0.3);
}

/** Per-station heat value normalised to [0, 1] (linear interpolation, clamped). */
function heatAtStations(spec: Spec, heat: { x_m: number[]; value: number[] }): Float64Array | null {
  const pts: [number, number][] = [];
  const m = Math.min(heat.x_m?.length ?? 0, heat.value?.length ?? 0);
  for (let i = 0; i < m; i++) if (fin(heat.x_m[i]) && fin(heat.value[i])) pts.push([heat.x_m[i], heat.value[i]]);
  if (!pts.length) return null;
  pts.sort((a, b) => a[0] - b[0]);
  let lo = Infinity, hi = -Infinity;
  for (const [, v] of pts) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const out = new Float64Array(spec.n);
  let k = 0;
  for (let i = 0; i < spec.n; i++) {
    const xi = spec.x[i];
    let v: number;
    if (xi <= pts[0][0]) v = pts[0][1];
    else if (xi >= pts[pts.length - 1][0]) v = pts[pts.length - 1][1];
    else {
      while (k < pts.length - 2 && pts[k + 1][0] < xi) k++;
      const [x0, v0] = pts[k], [x1, v1] = pts[k + 1];
      v = x1 > x0 ? v0 + ((v1 - v0) * (xi - x0)) / (x1 - x0) : v0;
    }
    out[i] = hi > lo ? (v - lo) / (hi - lo) : 0.5;
  }
  return out;
}

// ─── geometry ────────────────────────────────────────────────────────────
class GeoBuilder {
  readonly pos: number[] = [];
  readonly idx: number[] = [];
  private readonly tmp: P3 = [0, 0, 0];

  /** rows × cols vertex grid, quads between neighbours. */
  grid(rows: number, cols: number, at: (i: number, j: number, out: P3) => void): void {
    const base = this.pos.length / 3;
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) { at(i, j, this.tmp); this.pos.push(this.tmp[0], this.tmp[1], this.tmp[2]); }
    }
    for (let i = 0; i < rows - 1; i++) {
      for (let j = 0; j < cols - 1; j++) {
        const a = base + i * cols + j, b = a + cols;
        this.idx.push(a, b, a + 1, a + 1, b, b + 1);
      }
    }
  }

  revolve(x: ArrayLike<number>, r: ArrayLike<number>): void {
    this.grid(x.length, REV_SEGS + 1, (i, j, o) => {
      const th = (TAU * j) / REV_SEGS;
      o[0] = x[i]; o[1] = r[i] * Math.cos(th); o[2] = r[i] * Math.sin(th);
    });
  }

  annulus(x: number, r0: number, r1: number): void {
    this.grid(2, REV_SEGS + 1, (i, j, o) => {
      const th = (TAU * j) / REV_SEGS, r = i ? r1 : r0;
      o[0] = x; o[1] = r * Math.cos(th); o[2] = r * Math.sin(th);
    });
  }

  build(): THREE.BufferGeometry {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.pos, 3));
    g.setIndex(this.idx);
    g.computeVertexNormals();
    return g;
  }
}

class LineBuilder {
  readonly pos: number[] = [];
  seg(a: P3, b: P3): void { this.pos.push(a[0], a[1], a[2], b[0], b[1], b[2]); }
  circle(x: number, r: number): void {
    for (let j = 0; j < REV_SEGS; j++) {
      const t0 = (TAU * j) / REV_SEGS, t1 = (TAU * (j + 1)) / REV_SEGS;
      this.seg([x, r * Math.cos(t0), r * Math.sin(t0)], [x, r * Math.cos(t1), r * Math.sin(t1)]);
    }
  }
  arcSegs(a: P3, b: P3, n: number): void {
    const p: P3 = [0, 0, 0], q: P3 = [0, 0, 0];
    for (let j = 0; j < n; j++) { arc(a, b, j / n, p); arc(a, b, (j + 1) / n, q); this.seg([...p], [...q]); }
  }
  build(): THREE.BufferGeometry {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.pos, 3));
    return g;
  }
}

/** One pitch of the milled liner outer surface: channel 0 floor + its L wall, the land, channel 1's R wall. */
function buildSector(spec: Spec, ch: ChannelSpec): THREE.BufferGeometry {
  const b = new GeoBuilder();
  const { n } = spec, { nFloor, nLand, alpha } = ch;
  const fR1 = ch.fR.map((p) => rotX(p, alpha)), tR1 = ch.tR.map((p) => rotX(p, alpha));
  b.grid(n, nFloor + 1, (i, j, o) => arc(ch.fR[i], ch.fL[i], j / nFloor, o));
  b.grid(n, 2, (i, j, o) => { const p = j ? ch.tL[i] : ch.fL[i]; o[0] = p[0]; o[1] = p[1]; o[2] = p[2]; });
  b.grid(n, nLand + 1, (i, j, o) => arc(ch.tL[i], tR1[i], j / nLand, o));
  b.grid(n, 2, (i, j, o) => { const p = j ? fR1[i] : tR1[i]; o[0] = p[0]; o[1] = p[1]; o[2] = p[2]; });
  for (const i of [0, n - 1]) {   // land end faces
    b.grid(2, nLand + 1, (r, j, o) => (r ? arc(ch.tL[i], tR1[i], j / nLand, o) : arc(ch.fL[i], fR1[i], j / nLand, o)));
  }
  return b.build();
}

/** Closed coolant body of channel 0: floor, walls, top and end caps. */
function buildCoolant(spec: Spec, ch: ChannelSpec): THREE.BufferGeometry {
  const b = new GeoBuilder();
  const { n } = spec, { nFloor } = ch;
  const cp = (p: P3, o: P3): void => { o[0] = p[0]; o[1] = p[1]; o[2] = p[2]; };
  b.grid(n, nFloor + 1, (i, j, o) => arc(ch.fR[i], ch.fL[i], j / nFloor, o));
  b.grid(n, 2, (i, j, o) => cp(j ? ch.tL[i] : ch.fL[i], o));
  b.grid(n, nFloor + 1, (i, j, o) => arc(ch.tL[i], ch.tR[i], j / nFloor, o));
  b.grid(n, 2, (i, j, o) => cp(j ? ch.fR[i] : ch.tR[i], o));
  for (const i of [0, n - 1]) {
    b.grid(2, nFloor + 1, (r, j, o) => (r ? arc(ch.tR[i], ch.tL[i], j / nFloor, o) : arc(ch.fR[i], ch.fL[i], j / nFloor, o)));
  }
  return b.build();
}

// ─── palette ─────────────────────────────────────────────────────────────
interface Palette {
  surface: THREE.Color; surface2: THREE.Color; ink: THREE.Color; ink3: THREE.Color;
  line2: THREE.Color; hot: THREE.Color; cool: THREE.Color; dark: boolean;
}

let probe: CanvasRenderingContext2D | null | undefined;
function cssColor(cs: CSSStyleDeclaration, name: string, fallback: string): THREE.Color {
  const out = new THREE.Color(fallback);
  const raw = cs.getPropertyValue(name).trim();
  if (!raw) return out;
  if (probe === undefined) probe = document.createElement("canvas").getContext("2d");
  if (!probe) { if (/^#|^rgb|^hsl/i.test(raw)) out.setStyle(raw); return out; }
  probe.fillStyle = "#000"; probe.fillStyle = raw;              // canvas normalises any CSS colour
  const norm = String(probe.fillStyle);
  if (/^#[0-9a-f]{6}$/i.test(norm) || /^rgba?\(/i.test(norm)) out.setStyle(norm);
  return out;
}

function readPalette(): Palette {
  const cs = getComputedStyle(document.documentElement);
  const surface = cssColor(cs, "--surface", "#fbfaf6");
  const hsl = { h: 0, s: 0, l: 0 };
  surface.getHSL(hsl);
  return {
    surface, surface2: cssColor(cs, "--surface-2", "#f4f1e9"), ink: cssColor(cs, "--ink", "#1a1c1e"),
    ink3: cssColor(cs, "--ink-3", "#7b7f84"), line2: cssColor(cs, "--line-2", "#cbc2ae"),
    hot: cssColor(cs, "--hot", "#d4461a"), cool: cssColor(cs, "--cool", "#0079ad"), dark: hsl.l < 0.4,
  };
}

const mix = (a: THREE.Color, b: THREE.Color, t: number): THREE.Color => a.clone().lerp(b, t);

// ─── hatch textures for section faces ────────────────────────────────────
interface Hatch { canvas: HTMLCanvasElement; tex: THREE.CanvasTexture; dir: 1 | -1 }

function makeHatch(dir: 1 | -1): Hatch {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 32;
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return { canvas, tex, dir };
}

function drawHatch(h: Hatch, base: THREE.Color, line: THREE.Color): void {
  const g = h.canvas.getContext("2d");
  if (!g) return;
  const S = h.canvas.width;
  g.fillStyle = `#${base.getHexString()}`;
  g.fillRect(0, 0, S, S);
  g.strokeStyle = `#${line.getHexString()}`;
  g.lineWidth = 3;
  g.lineCap = "square";
  for (const off of [-S, 0, S]) {
    g.beginPath();
    if (h.dir > 0) { g.moveTo(off, S); g.lineTo(off + S, 0); } else { g.moveTo(off, 0); g.lineTo(off + S, S); }
    g.stroke();
  }
  h.tex.needsUpdate = true;
}

// ─── section faces at a cut half-plane θ = phi ───────────────────────────
class SectionBuilder {
  readonly pos: number[] = [];
  readonly uv: number[] = [];
  readonly idx: number[] = [];
  private readonly c: number;
  private readonly s: number;
  private readonly hs: number;
  constructor(c: number, s: number, hs: number) { this.c = c; this.s = s; this.hs = hs; }
  band(x0: number, a0: number, b0: number, x1: number, a1: number, b1: number): void {
    const base = this.pos.length / 3;
    for (const [x, r] of [[x0, a0], [x0, b0], [x1, a1], [x1, b1]]) {
      this.pos.push(x, r * this.c, r * this.s);
      this.uv.push(x / this.hs, r / this.hs);
    }
    this.idx.push(base, base + 2, base + 1, base + 1, base + 2, base + 3);
  }
  build(): THREE.BufferGeometry | null {
    if (!this.idx.length) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.pos, 3));
    g.setAttribute("uv", new THREE.Float32BufferAttribute(this.uv, 2));
    g.setIndex(this.idx);
    return g;
  }
}

function inChannel(ch: ChannelSpec, i: number, phi: number): boolean {
  const j = Math.min(i + 1, ch.thetaC.length - 1);
  const tc = ch.thetaC[i] + wrapPi(ch.thetaC[j] - ch.thetaC[i]) / 2;
  const hw = (ch.halfW[i] + ch.halfW[j]) / 2;
  let d = wrapPi(phi - tc);
  d -= ch.alpha * Math.round(d / ch.alpha);
  return Math.abs(d) < hw;
}

interface SectionGeo { a: THREE.BufferGeometry | null; b: THREE.BufferGeometry | null; cool: THREE.BufferGeometry | null; lines: THREE.BufferGeometry }

function buildSection(spec: Spec, phi: number, opts: ViewOpts): SectionGeo {
  const c = Math.cos(phi), s = Math.sin(phi);
  const A = new SectionBuilder(c, s, spec.hatch), B = new SectionBuilder(c, s, spec.hatch), C = new SectionBuilder(c, s, spec.hatch);
  const L = new LineBuilder();
  const { x, rIn, rFloor, rTop, rOut, channels: ch } = spec;
  const closeout = spec.hasCloseout && opts.closeout;
  const pt = (xx: number, r: number): P3 => [xx, r * c, r * s];
  const line = (i: number, r: Float64Array): void => L.seg(pt(x[i], r[i]), pt(x[i + 1], r[i + 1]));
  let prevIn = false;
  for (let i = 0; i < spec.n - 1; i++) {
    const inside = ch ? inChannel(ch, i, phi) : false;
    if (inside) {
      A.band(x[i], rIn[i], rFloor[i], x[i + 1], rIn[i + 1], rFloor[i + 1]);
      if (opts.channels) C.band(x[i], rFloor[i], rTop[i], x[i + 1], rFloor[i + 1], rTop[i + 1]);
    } else {
      A.band(x[i], rIn[i], rTop[i], x[i + 1], rIn[i + 1], rTop[i + 1]);
    }
    if (closeout) B.band(x[i], rTop[i], rOut[i], x[i + 1], rTop[i + 1], rOut[i + 1]);

    line(i, rIn);
    if (inside) line(i, rFloor);
    if (closeout || !inside || opts.channels) line(i, rTop);
    if (closeout) line(i, rOut);
    if (i > 0 && inside !== prevIn) L.seg(pt(x[i], rFloor[i]), pt(x[i], rTop[i]));
    prevIn = inside;
  }
  const outer = closeout ? rOut : rTop;
  for (const i of [0, spec.n - 1]) L.seg(pt(x[i], rIn[i]), pt(x[i], outer[i]));
  return { a: A.build(), b: B.build(), cool: C.build(), lines: L.build() };
}

// ─── imperative viewer core ──────────────────────────────────────────────
interface Model {
  inner: THREE.Mesh;
  closeoutParts: THREE.Object3D[];
  coolant: THREE.InstancedMesh | null;
  objects: THREE.Object3D[];
  outline: THREE.Vector3[];   // world-space points on the outer surface, for framing
}

interface Mats {
  inner: THREE.MeshStandardMaterial;
  metal: THREE.MeshStandardMaterial;
  closeout: THREE.MeshStandardMaterial;
  coolant: THREE.MeshStandardMaterial;
  line: THREE.LineBasicMaterial;
  secA: THREE.MeshBasicMaterial;
  secB: THREE.MeshBasicMaterial;
  secCool: THREE.MeshBasicMaterial;
  secLine: THREE.LineBasicMaterial;
}

class ViewerCore {
  private readonly host: HTMLElement;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);
  private readonly controls: OrbitControls;
  private readonly root = new THREE.Group();
  private readonly sectionGroup = new THREE.Group();
  private readonly hemi = new THREE.HemisphereLight(0xffffff, 0x888888, 1.6);
  private readonly key = new THREE.DirectionalLight(0xffffff, 1.6);
  private readonly rim = new THREE.DirectionalLight(0xffffff, 0.5);
  private readonly hatchA = makeHatch(1);
  private readonly hatchB = makeHatch(-1);
  private readonly mats: Mats;
  private readonly planes = [new THREE.Plane(), new THREE.Plane()];
  private readonly ro: ResizeObserver;
  private readonly mo: MutationObserver;
  private palette: Palette;
  private spec: Spec | null = null;
  private model: Model | null = null;
  private heat: Float64Array | null = null;
  private opts: ViewOpts = { cut: "quarter", closeout: true, channels: true };
  private raf = 0;
  private userMoved = false;
  private disposed = false;

  constructor(host: HTMLElement) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.localClippingEnabled = true;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const cv = this.renderer.domElement;
    cv.style.display = "block"; cv.style.width = "100%"; cv.style.height = "100%";
    host.appendChild(cv);

    const std = (p: THREE.MeshStandardMaterialParameters = {}): THREE.MeshStandardMaterial => new THREE.MeshStandardMaterial({
      roughness: 0.82, metalness: 0.1, side: THREE.DoubleSide,
      ...p,
    });
    const aniso = this.renderer.capabilities.getMaxAnisotropy();
    this.hatchA.tex.anisotropy = this.hatchB.tex.anisotropy = aniso;
    const basic = (p: THREE.MeshBasicMaterialParameters): THREE.MeshBasicMaterial => new THREE.MeshBasicMaterial({
      side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 0.5, polygonOffsetUnits: 1, ...p,
    });
    this.mats = {
      inner: std({ vertexColors: true }),
      // channel walls are often seen edge-on; a slope-scaled offset keeps their depth
      // sparkles behind the liner, and the coolant wins where it touches the groove
      metal: std({ polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }),
      closeout: std({ roughness: 0.88 }),
      coolant: std({ roughness: 0.6, metalness: 0.05, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 0 }),
      line: new THREE.LineBasicMaterial({ transparent: true, opacity: 0.55 }),
      secA: basic({ map: this.hatchA.tex }),
      secB: basic({ map: this.hatchB.tex }),
      secCool: basic({}),
      secLine: new THREE.LineBasicMaterial({ transparent: true, opacity: 0.7 }),
    };

    this.scene.add(this.hemi, this.camera, this.root);
    this.key.position.set(1.2, 2.0, 1.0);    // camera-relative key light, aimed at the origin
    this.rim.position.set(-2.0, -0.6, -1.0);
    this.camera.add(this.key, this.rim);
    this.root.add(this.sectionGroup);

    this.controls = new OrbitControls(this.camera, cv);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.zoomToCursor = true;
    this.controls.minDistance = 0.02;
    this.controls.maxDistance = 14;
    this.controls.addEventListener("change", this.invalidate);
    this.controls.addEventListener("start", this.onStart);

    this.palette = readPalette();
    this.applyPalette();

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.mo = new MutationObserver(() => { this.palette = readPalette(); this.applyPalette(); this.invalidate(); });
    this.mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
    this.resize();
    this.fitView();
  }

  // ── rendering ──
  readonly invalidate = (): void => {
    if (!this.raf && !this.disposed) this.raf = requestAnimationFrame(this.frame);
  };

  private readonly frame = (): void => {
    this.raf = 0;
    if (this.disposed) return;
    const moving = this.controls.update();
    const d = this.camera.position.distanceTo(this.controls.target);
    this.camera.near = Math.max(1e-4, d * 0.004);
    this.camera.far = d * 4 + 10;
    this.camera.updateProjectionMatrix();
    this.renderer.render(this.scene, this.camera);
    if (moving) this.invalidate();
  };

  private readonly onStart = (): void => { this.userMoved = true; };

  private resize(): void {
    const w = Math.max(1, this.host.clientWidth), h = Math.max(1, this.host.clientHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    if (!this.userMoved) this.fitView();
    this.invalidate();
  }

  /** Frame the model from the default 3/4 exit-side direction. */
  fitView(): void {
    const back = CAM_DIR, right = new THREE.Vector3(0, 1, 0).cross(back).normalize(), up = back.clone().cross(right);
    const tanV = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)), tanH = tanV * this.camera.aspect;
    let dist = 0;
    const pts = this.model?.outline ?? [];
    for (const p of pts) {
      const c = p.dot(back);
      dist = Math.max(dist, c + Math.abs(p.dot(right)) / tanH, c + Math.abs(p.dot(up)) / tanV);
    }
    if (!pts.length) dist = 4.5;
    dist *= 1.1;
    // flush any residual damping motion, otherwise it keeps rotating after the reset
    this.controls.enableDamping = false;
    this.controls.update();
    this.controls.target.set(0, 0, 0);
    this.camera.position.copy(back).multiplyScalar(dist);
    this.camera.up.set(0, 1, 0);
    this.camera.lookAt(0, 0, 0);
    this.controls.update();
    this.controls.enableDamping = true;
    this.invalidate();
  }

  resetView(): void {
    this.userMoved = false;
    this.fitView();
  }

  // ── data ──
  setSpec(spec: Spec | null): void {
    if (spec === this.spec) return;
    this.clearModel();
    this.spec = spec;
    if (spec) this.buildModel(spec);
    this.applyInnerColors();
    this.applyOptions();
    if (!this.userMoved) this.fitView();
    this.invalidate();
  }

  setHeat(heat: Float64Array | null): void {
    this.heat = heat;
    this.applyInnerColors();
    this.invalidate();
  }

  setOptions(opts: ViewOpts): void {
    this.opts = opts;
    this.applyOptions();
    this.invalidate();
  }

  private buildModel(spec: Spec): void {
    const s = 2 / Math.max(spec.xMax - spec.xMin, 2 * spec.rMax, 1e-9);
    this.root.scale.setScalar(s);
    this.root.position.set((-s * (spec.xMin + spec.xMax)) / 2, 0, 0);
    const { mats } = this;
    const objects: THREE.Object3D[] = [];
    const add = <T extends THREE.Object3D>(o: T): T => { o.frustumCulled = false; objects.push(o); this.root.add(o); return o; };
    const { x, rIn, rFloor, rTop, rOut, channels: ch, n } = spec;

    // hot-gas surface (vertex coloured)
    const gi = new GeoBuilder();
    gi.revolve(x, rIn);
    const innerGeo = gi.build();
    innerGeo.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(innerGeo.getAttribute("position").count * 3), 3));
    const inner = add(new THREE.Mesh(innerGeo, mats.inner));

    // liner body: end rings (+ plain outer surface when there are no channels)
    const gl = new GeoBuilder();
    const linerTop = ch ? rFloor : rTop;
    gl.annulus(x[0], rIn[0], linerTop[0]);
    gl.annulus(x[n - 1], rIn[n - 1], linerTop[n - 1]);
    if (!ch) gl.revolve(x, rTop);
    add(new THREE.Mesh(gl.build(), mats.metal));

    const lines = new LineBuilder();
    for (const i of [0, n - 1]) lines.circle(x[i], rIn[i]);
    if (!ch) for (const i of [0, n - 1]) lines.circle(x[i], rTop[i]);

    let coolant: THREE.InstancedMesh | null = null;
    if (ch) {
      const m = new THREE.Matrix4();
      const sector = add(new THREE.InstancedMesh(buildSector(spec, ch), mats.metal, ch.N));
      coolant = add(new THREE.InstancedMesh(buildCoolant(spec, ch), mats.coolant, ch.N));
      for (let k = 0; k < ch.N; k++) {
        m.makeRotationX(k * ch.alpha);
        sector.setMatrixAt(k, m);
        coolant.setMatrixAt(k, m);
      }
      sector.instanceMatrix.needsUpdate = coolant.instanceMatrix.needsUpdate = true;
      // channel outlines on the two end faces
      for (const i of [0, n - 1]) {
        for (let k = 0; k < ch.N; k++) {
          const a = k * ch.alpha;
          const fL = rotX(ch.fL[i], a), fR = rotX(ch.fR[i], a), tL = rotX(ch.tL[i], a), tR = rotX(ch.tR[i], a);
          const tR1 = rotX(ch.tR[i], a + ch.alpha);
          lines.seg(tR, fR);
          lines.arcSegs(fR, fL, ch.nFloor);
          lines.seg(fL, tL);
          lines.arcSegs(tL, tR1, ch.nLand);
        }
      }
    }
    add(new THREE.LineSegments(lines.build(), mats.line));

    const closeoutParts: THREE.Object3D[] = [];
    if (spec.hasCloseout) {
      const gc = new GeoBuilder();
      gc.revolve(x, rOut);
      gc.annulus(x[0], rTop[0], rOut[0]);
      gc.annulus(x[n - 1], rTop[n - 1], rOut[n - 1]);
      closeoutParts.push(add(new THREE.Mesh(gc.build(), mats.closeout)));
      const lc = new LineBuilder();
      for (const i of [0, n - 1]) { lc.circle(x[i], rOut[i]); if (ch) lc.circle(x[i], rTop[i]); }
      closeoutParts.push(add(new THREE.LineSegments(lc.build(), mats.line)));
    }

    const outline: THREE.Vector3[] = [];
    const every = Math.max(1, Math.floor(n / 40));
    const idx: number[] = [];
    for (let i = 0; i < n - 1; i += every) idx.push(i);
    idx.push(n - 1);
    for (const i of idx) {
      for (let k = 0; k < 36; k++) {
        const th = (TAU * k) / 36;
        outline.push(new THREE.Vector3(s * x[i], s * rOut[i] * Math.cos(th), s * rOut[i] * Math.sin(th)).add(this.root.position));
      }
    }
    this.model = { inner, closeoutParts, coolant, objects, outline };
  }

  private clearModel(): void {
    if (this.model) {
      for (const o of this.model.objects) {
        this.root.remove(o);
        if (o instanceof THREE.Mesh || o instanceof THREE.LineSegments) o.geometry.dispose();
        if (o instanceof THREE.InstancedMesh) o.dispose();
      }
      this.model = null;
    }
    this.clearSection();
  }

  private clearSection(): void {
    for (const o of [...this.sectionGroup.children]) {
      this.sectionGroup.remove(o);
      if (o instanceof THREE.Mesh || o instanceof THREE.LineSegments) o.geometry.dispose();
    }
  }

  /** Cut half-planes (θ values), snapped onto channel centre lines so the section cuts through the channels. */
  private cutAngles(): [number, number] | null {
    const { cut } = this.opts;
    if (cut === "full") return null;
    const ch = this.spec?.channels;
    const snap = (a: number): number => (ch ? ch.thetaMid + ch.alpha * Math.round(wrapPi(a - ch.thetaMid) / ch.alpha) : a);
    if (cut === "half") { const p1 = snap(PHI_CAM - Math.PI / 2); return [p1, p1 + Math.PI]; }
    const p1 = snap(PHI_CAM - Math.PI / 4);
    let p2 = snap(PHI_CAM + Math.PI / 4);
    while (p2 <= p1) p2 += TAU;
    return [p1, p2];
  }

  private applyOptions(): void {
    const { mats, model, spec, opts } = this;
    const angles = spec ? this.cutAngles() : null;
    if (angles) {
      const [p1, p2] = angles;
      // clipped (removed) where both are negative: θ ∈ (p1, p2)
      this.planes[0].set(new THREE.Vector3(0, Math.sin(p1), -Math.cos(p1)), 0);
      this.planes[1].set(new THREE.Vector3(0, -Math.sin(p2), Math.cos(p2)), 0);
    }
    for (const m of [mats.inner, mats.metal, mats.closeout, mats.coolant, mats.line]) {
      m.clippingPlanes = angles ? this.planes : null;
      m.clipIntersection = true;
      m.needsUpdate = true;
    }
    if (model) {
      for (const o of model.closeoutParts) o.visible = opts.closeout;
      if (model.coolant) model.coolant.visible = opts.channels;
    }
    this.clearSection();
    if (spec && angles) {
      for (const phi of angles) {
        const sg = buildSection(spec, phi, opts);
        if (sg.a) this.sectionGroup.add(new THREE.Mesh(sg.a, mats.secA));
        if (sg.b) this.sectionGroup.add(new THREE.Mesh(sg.b, mats.secB));
        if (sg.cool) this.sectionGroup.add(new THREE.Mesh(sg.cool, mats.secCool));
        this.sectionGroup.add(new THREE.LineSegments(sg.lines, mats.secLine));
      }
      for (const o of this.sectionGroup.children) o.frustumCulled = false;
    }
  }

  // ── colours ──
  private colors(): { metal: THREE.Color; closeout: THREE.Color; innerBase: THREE.Color; heatLo: THREE.Color } {
    const P = this.palette, k = P.dark ? 1.75 : 1;
    const metal = mix(P.surface2, P.ink3, 0.3 * k);
    return {
      metal,
      closeout: mix(P.surface2, P.ink3, 0.17 * k),
      innerBase: mix(mix(P.surface2, P.ink3, 0.22 * k), P.hot, P.dark ? 0.035 : 0.08),
      heatLo: mix(P.surface, P.ink3, 0.14 * k),
    };
  }

  private applyPalette(): void {
    const P = this.palette, { mats } = this, c = this.colors();
    mats.metal.color.copy(c.metal);
    mats.closeout.color.copy(c.closeout);
    mats.coolant.color.copy(mix(P.cool, P.surface, P.dark ? 0.08 : 0.12));
    mats.line.color.copy(P.dark ? mix(P.ink3, P.ink, 0.2) : P.ink3);
    mats.line.opacity = P.dark ? 0.45 : 0.55;
    mats.secLine.color.copy(P.dark ? mix(P.ink3, P.ink, 0.5) : mix(P.ink3, P.ink, 0.5));
    mats.secCool.color.copy(mix(P.cool, P.surface, 0.18));
    drawHatch(this.hatchA, mix(P.surface2, P.ink3, P.dark ? 0.42 : 0.3), mix(P.ink3, P.ink, P.dark ? 0.15 : 0.35));
    drawHatch(this.hatchB, mix(P.surface2, P.ink3, P.dark ? 0.3 : 0.18), mix(P.ink3, P.ink, P.dark ? 0.05 : 0.2));
    this.hemi.color.set(0xffffff);
    this.hemi.groundColor.copy(mix(P.surface2, P.ink3, 0.5));
    this.hemi.intensity = P.dark ? 1.25 : 1.5;
    this.key.intensity = P.dark ? 1.5 : 1.7;
    this.rim.intensity = P.dark ? 0.45 : 0.35;
    this.applyInnerColors();
  }

  private applyInnerColors(): void {
    const model = this.model, spec = this.spec;
    if (!model || !spec) return;
    const attr = model.inner.geometry.getAttribute("color") as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    const cols = REV_SEGS + 1, c = this.colors(), heat = this.heat && this.heat.length === spec.n ? this.heat : null;
    const tmp = new THREE.Color();
    for (let i = 0; i < spec.n; i++) {
      if (heat) tmp.copy(c.heatLo).lerp(this.palette.hot, Math.min(1, Math.max(0, heat[i])));
      else tmp.copy(c.innerBase);
      for (let j = 0; j < cols; j++) {
        const o = (i * cols + j) * 3;
        arr[o] = tmp.r; arr[o + 1] = tmp.g; arr[o + 2] = tmp.b;
      }
    }
    attr.needsUpdate = true;
  }

  dispose(): void {
    this.disposed = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.ro.disconnect();
    this.mo.disconnect();
    this.controls.removeEventListener("change", this.invalidate);
    this.controls.removeEventListener("start", this.onStart);
    this.controls.dispose();
    this.clearModel();
    for (const m of Object.values(this.mats) as THREE.Material[]) m.dispose();
    this.hatchA.tex.dispose();
    this.hatchB.tex.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer.domElement.remove();
  }
}

// ─── React component ─────────────────────────────────────────────────────
const CUTS: { id: CutMode; label: string }[] = [
  { id: "full", label: "Full" },
  { id: "quarter", label: "Quarter cut" },
  { id: "half", label: "Half cut" },
];

export default function EngineViewer({ assembly = null, contour = null, heat = null, height = 360 }: EngineViewerProps): JSX.Element {
  const hostRef = useRef<HTMLDivElement>(null);
  const coreRef = useRef<ViewerCore | null>(null);
  const [cut, setCut] = useState<CutMode>("quarter");
  const [showCloseout, setShowCloseout] = useState(true);
  const [showChannels, setShowChannels] = useState(true);

  const spec = useMemo<Spec | null>(() => {
    const fromAssembly = assembly ? specFromAssembly(assembly) : null;
    return fromAssembly ?? (contour ? specFromContour(contour) : null);
  }, [assembly, contour]);
  const heatSt = useMemo(() => (spec && heat ? heatAtStations(spec, heat) : null), [spec, heat]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let core: ViewerCore;
    try { core = new ViewerCore(host); } catch { return; }   // no WebGL: leave the panel empty
    coreRef.current = core;
    return () => { core.dispose(); coreRef.current = null; };
  }, []);
  useEffect(() => { coreRef.current?.setSpec(spec); }, [spec]);
  useEffect(() => { coreRef.current?.setHeat(heatSt); }, [heatSt, spec]);
  useEffect(() => {
    coreRef.current?.setOptions({ cut, closeout: showCloseout, channels: showChannels });
  }, [cut, showCloseout, showChannels, spec]);

  const hasChannels = !!spec?.channels;
  const hasCloseout = !!spec?.hasCloseout;

  return (
    <div className="viewer3d" style={{ height, aspectRatio: "auto" }}>
      <div ref={hostRef} style={{ position: "absolute", inset: 0 }} />
      {!spec && (
        <div className="muted" style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", fontSize: 12.5, pointerEvents: "none" }}>
          No geometry to display
        </div>
      )}
      {spec && <div className="overlay">
        <div className="seg" role="group" aria-label="Cutaway">
          {CUTS.map((c) => (
            <button key={c.id} type="button" className={cut === c.id ? "on" : undefined} aria-pressed={cut === c.id} onClick={() => setCut(c.id)}>
              {c.label}
            </button>
          ))}
        </div>
        {hasCloseout && (
          <label className="chip" style={{ cursor: "pointer" }}>
            <input type="checkbox" checked={showCloseout} onChange={(e) => setShowCloseout(e.target.checked)} style={{ margin: 0, accentColor: "var(--ink-2)" }} />
            Closeout
          </label>
        )}
        {hasChannels && (
          <label className="chip" style={{ cursor: "pointer" }}>
            <input type="checkbox" checked={showChannels} onChange={(e) => setShowChannels(e.target.checked)} style={{ margin: 0, accentColor: "var(--cool)" }} />
            Channels
          </label>
        )}
        <span style={{ flex: 1 }} />
        <button type="button" className="btn btn-sm" onClick={() => coreRef.current?.resetView()} style={{ background: "color-mix(in srgb, var(--surface) 85%, transparent)" }}>
          Reset view
        </button>
      </div>}
    </div>
  );
}
