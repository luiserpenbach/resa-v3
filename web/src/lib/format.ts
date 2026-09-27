// Number / time formatting for engineering readouts.

export function fmt(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Significant-figure formatting without exponent noise for typical ranges. */
export function sig(v: number | null | undefined, n = 3): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e6 || a < 1e-4) return v.toExponential(n - 1);
  const d = Math.max(0, n - 1 - Math.floor(Math.log10(a)));
  return fmt(v, Math.min(d, 6));
}

/** Value with an auto-scaled SI prefix: force(1520) -> ["1.52", "kN"]. */
export function scaled(v: number, unit: string, n = 3): [string, string] {
  const a = Math.abs(v);
  if (a >= 1e6) return [sig(v / 1e6, n), `M${unit}`];
  if (a >= 1e3) return [sig(v / 1e3, n), `k${unit}`];
  return [sig(v, n), unit];
}

export function relTime(iso: string | undefined): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 14) return `${d} d ago`;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (lo === hi) { lo -= 1; hi += 1; }
  const span = hi - lo;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const start = Math.ceil(lo / step - 1e-9) * step;
  const out: number[] = [];
  for (let v = start; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

export function tickLabel(v: number, step: number): string {
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e5 || (a < 1e-3 && a > 0)) return v.toExponential(0).replace("e+", "e");
  const d = Math.max(0, -Math.floor(Math.log10(Math.abs(step) || 1)));
  return v.toFixed(Math.min(d, 4));
}
