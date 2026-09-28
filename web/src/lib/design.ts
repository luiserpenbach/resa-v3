// Engine-design model helpers: path access, templates, smart defaults,
// friendly labels (no config jargon in the UI) and version KPIs.
import type { Catalog, CoolingResult, Design, HeatFluxResult, Json, PerformanceResult } from "./api";

export type Path = (string | number)[];

export function getPath(obj: Json, path: Path): Json {
  let o = obj;
  for (const k of path) {
    if (o == null) return undefined;
    o = o[k];
  }
  return o;
}

/** Immutable set; creates missing objects along the way. */
export function setPath<T extends Json>(obj: T, path: Path, value: Json): T {
  if (path.length === 0) return value;
  const [k, ...rest] = path;
  const base: Json = Array.isArray(obj) ? [...obj] : { ...(obj ?? {}) };
  base[k] = setPath(base[k], rest, value);
  return base;
}

export const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
export const pathKey = (p: Path) => p.join(".");

// ─── propellants ──────────────────────────────────────────────────────────
export type PropChoice = Catalog["propellants"][number];

export function propellantBlock(ox: PropChoice, fuel: PropChoice) {
  return {
    name: `${short(ox)}/${short(fuel)}`,
    oxidizer: ox.fluid ?? ox.cea_name,
    fuel: fuel.fluid ?? fuel.cea_name,
    ox_temp_K: ox.temperature_K,
    fuel_temp_K: fuel.temperature_K,
    cea_oxidizer: ox.cea_name,
    cea_fuel: fuel.cea_name,
    ox_phase: ox.phase,
    fuel_phase: fuel.phase,
  };
}

function short(p: PropChoice): string {
  const m = p.label.match(/\(([^)]+)\)/);
  return m ? m[1] : p.label.split(" ")[0];
}

/** Which catalog entry a design's propellant side corresponds to. */
export function matchPropellant(catalog: Catalog, design: Design, side: "oxidizer" | "fuel"): PropChoice | undefined {
  const pr = design.propellants ?? {};
  const cea = side === "oxidizer" ? pr.cea_oxidizer : pr.cea_fuel;
  const fluid = side === "oxidizer" ? pr.oxidizer : pr.fuel;
  const phase = side === "oxidizer" ? pr.ox_phase : pr.fuel_phase;
  const list = catalog.propellants.filter((p) => p.role === side);
  const norm = (s: string | null | undefined) => (s ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
  return (
    list.find((p) => norm(p.cea_name) === norm(cea) && (!phase || p.phase === phase)) ??
    list.find((p) => norm(p.cea_name) === norm(cea)) ??
    list.find((p) => norm(p.fluid) === norm(fluid) && (!phase || p.phase === phase)) ??
    list.find((p) => norm(p.fluid) === norm(fluid))
  );
}

// ─── templates ────────────────────────────────────────────────────────────
export interface QuickSpec {
  name: string;
  ox: PropChoice;
  fuel: PropChoice;
  thrust_N: number;
  pc_bar: number;
  of_ratio: number | null;
  ambient: "sea_level" | "vacuum";
}

export function engineTag(name: string): string {
  const t = name.trim().replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[^A-Za-z0-9]+/, "").slice(0, 64);
  return t || "ENGINE";
}

export function newDesign(spec: QuickSpec): Design {
  const vacuum = spec.ambient === "vacuum";
  return {
    engine: engineTag(spec.name),
    description: "",
    propellants: propellantBlock(spec.ox, spec.fuel),
    combustion: { backend: "cea", nozzle_flow: "equilibrium", use_delivery_temperatures: true },
    chamber: {
      contraction_ratio: spec.thrust_N < 2000 ? 8 : spec.thrust_N < 20000 ? 5 : 3.5,
      l_star_m: 1.0,
      contour: "rao_bell",
      bell_fraction: 0.8,
      conv_half_angle_deg: 35,
      bartz_correction: 1.0,
      n_stations: 200,
    },
    operating_point: {
      thrust_N: spec.thrust_N,
      pc_bar: spec.pc_bar,
      eta_cstar: 0.95,
      eta_cf: 0.98,
      eta_cf_source: "estimate",   // divergence + boundary-layer losses, no guesswork
      p_amb_bar: vacuum ? 0 : 1.01325,
      of_ratio: spec.of_ratio,
      eps: vacuum ? 50 : null,
      pe_bar: null,
    },
  };
}

export const DEFAULT_OF: Record<string, number> = {
  "lox/lh2": 6.0, "lox/lch4": 3.3, "lox/rp1": 2.6, "lox/ethanol": 1.6, "lox/methanol": 1.3, "lox/propane": 2.9,
  "lox/ammonia": 1.4, "gox/gh2": 4.0, "gox/ethanol": 1.6, "gox/lch4": 3.3, "n2o/ethanol": 4.0,
  "n2o/propane": 7.0, "n2o/lch4": 6.5, "n2o4/mmh": 2.0, "h2o2/rp1": 7.0, "h2o2/ethanol": 4.5,
};

// ─── cooling channels ─────────────────────────────────────────────────────
export interface ChannelDefaults {
  side: "fuel" | "oxidizer";
  count: number;
  height_m: number | number[][];   // constant, or [[x_m, h_m], ...] along the engine
  rib_m: number;
  wall_m: number;
  inlet_p_bar: number;
  inlet_T_K: number;
  material: string;
}

export function suggestChannels(design: Design, perf: PerformanceResult | null, catalog: Catalog | null): ChannelDefaults {
  const dt = perf?.geometry.throat_diameter_m ?? 0.03;
  const pc = perf?.performance.pc_bar ?? design.operating_point?.pc_bar ?? 20;
  const fuel = catalog ? matchPropellant(catalog, design, "fuel") : undefined;
  const side: "fuel" | "oxidizer" = !fuel || fuel.can_cool ? "fuel" : "oxidizer";
  const wall = dt > 0.02 ? 0.8e-3 : 0.5e-3;
  const pitch = Math.min(Math.max(0.05 * dt, 0.9e-3), 3e-3);
  const rib = Math.max(0.4 * pitch, 0.4e-3);
  const circ = 2 * Math.PI * (dt / 2 + wall + 0.5 * (pitch - rib));
  const count = Math.max(8, Math.round(circ / pitch));
  const pr = design.propellants ?? {};
  return {
    side, count, wall_m: wall, rib_m: round(rib, 5), height_m: round(Math.max(pitch - rib, 0.4e-3), 5) as number | number[][],
    inlet_p_bar: Math.round(1.8 * pc + 10),
    inlet_T_K: side === "fuel" ? pr.fuel_temp_K ?? 290 : pr.ox_temp_K ?? 290,
    material: dt < 0.015 ? "GRCop-42" : "Inconel 718",
  };
}

const round = (v: number, n: number) => Number(v.toFixed(n));

export function regenBlock(design: Design, c: ChannelDefaults) {
  const pr = design.propellants ?? {};
  const coolant = c.side === "fuel" ? pr.fuel : pr.oxidizer;
  const hydrogen = /hydrogen/i.test(coolant ?? "");
  return {
    meta: { name: `${design.engine ?? "engine"}_channels`, description: "", version: "1" },
    contour: { type: "from_engine" },
    channels: {
      count: c.count,
      inner_wall_thickness: c.wall_m,
      height: c.height_m,
      rib: { mode: "fixed_width", width: c.rib_m },
      helix: { profile: 0, interp: "pchip", handedness: "right" },
      min_channel_width: 0.3e-3,
    },
    geometry: { n_stations: 240, width_reference: "mid_height" },
    solver: {
      enabled: true,
      coolant,
      coolant_side: c.side,
      coolant_correlation: hydrogen ? "taylor" : "auto",
      inlet: { pressure_bar: c.inlet_p_bar, temperature_K: c.inlet_T_K, location: "nozzle_end" },
      wall: { material: c.material },
      roughness: 8e-6,
      skirt: { enabled: true, emissivity: 0.8, T_env_K: 300 },
    },
    export: { stl: true, step: false },
  };
}

// ─── labels (plain language, symbol as a hint) ────────────────────────────
export interface FieldInfo { label: string; unit?: string; scale?: number; digits?: number }

export const FIELDS: Record<string, FieldInfo> = {
  "engine": { label: "Engine tag" },
  "description": { label: "Description" },
  "propellants.oxidizer": { label: "Oxidizer" },
  "propellants.fuel": { label: "Fuel" },
  "propellants.ox_temp_K": { label: "Oxidizer delivery temperature", unit: "K" },
  "propellants.fuel_temp_K": { label: "Fuel delivery temperature", unit: "K" },
  "propellants.ox_phase": { label: "Oxidizer phase" },
  "propellants.fuel_phase": { label: "Fuel phase" },
  "propellants.fuel_temp_source": { label: "Fuel temperature from cooling outlet" },
  "propellants.ox_temp_source": { label: "Oxidizer temperature from cooling outlet" },
  "combustion.backend": { label: "Chemistry model" },
  "combustion.nozzle_flow": { label: "Nozzle flow model" },
  "combustion.use_delivery_temperatures": { label: "Use delivery temperatures" },
  "operating_point.thrust_N": { label: "Thrust", unit: "N" },
  "operating_point.pc_bar": { label: "Chamber pressure", unit: "bar" },
  "operating_point.of_ratio": { label: "Mixture ratio (O/F)" },
  "operating_point.eta_cstar": { label: "Combustion efficiency" },
  "operating_point.eta_cstar_tol": { label: "Combustion efficiency ±" },
  "operating_point.eta_cf": { label: "Nozzle efficiency" },
  "operating_point.eta_cf_source": { label: "Nozzle efficiency source" },
  "operating_point.p_amb_bar": { label: "Ambient pressure", unit: "bar" },
  "operating_point.eps": { label: "Nozzle area ratio" },
  "operating_point.pe_bar": { label: "Nozzle exit pressure", unit: "bar" },
  "analyze_point.mdot_ox_kg_s": { label: "Oxidizer flow", unit: "kg/s" },
  "analyze_point.mdot_fuel_kg_s": { label: "Fuel flow", unit: "kg/s" },
  "analyze_point.eta_cstar": { label: "Combustion efficiency" },
  "analyze_point.eta_cf": { label: "Nozzle efficiency" },
  "analyze_point.p_amb_bar": { label: "Ambient pressure", unit: "bar" },
  "geometry.throat_diameter_m": { label: "Throat diameter", unit: "mm", scale: 1e3 },
  "geometry.eps": { label: "Nozzle area ratio" },
  "geometry.exit_diameter_m": { label: "Exit diameter", unit: "mm", scale: 1e3 },
  "chamber.contraction_ratio": { label: "Contraction ratio" },
  "chamber.l_star_m": { label: "Characteristic length L*", unit: "m" },
  "chamber.contour": { label: "Nozzle shape" },
  "chamber.bell_fraction": { label: "Bell length", unit: "%", scale: 100 },
  "chamber.conv_half_angle_deg": { label: "Convergent angle", unit: "°" },
  "chamber.bartz_correction": { label: "Heat-transfer factor" },
  "chamber.bartz_correction_tol": { label: "Heat-transfer factor ±" },
  "chamber.rt_upstream_factor": { label: "Throat upstream radius", unit: "× Rt" },
  "chamber.rt_downstream_factor": { label: "Throat downstream radius", unit: "× Rt" },
  "chamber.rc_entrance_factor": { label: "Chamber entrance radius", unit: "× Rc" },
  "chamber.n_stations": { label: "Contour stations" },
  "chamber.theta_n_deg": { label: "Bell start angle", unit: "°" },
  "chamber.theta_e_deg": { label: "Bell exit angle", unit: "°" },
  "regen.channels.count": { label: "Number of channels" },
  "regen.channels.height": { label: "Channel height", unit: "mm", scale: 1e3 },
  "regen.channels.rib.width": { label: "Rib width", unit: "mm", scale: 1e3 },
  "regen.channels.rib.mode": { label: "Rib width mode" },
  "regen.channels.inner_wall_thickness": { label: "Hot-wall thickness", unit: "mm", scale: 1e3 },
  "regen.channels.helix.profile": { label: "Spiral angle", unit: "°" },
  "regen.channels.start_x": { label: "Channels start", unit: "mm", scale: 1e3 },
  "regen.channels.stop_x": { label: "Channels end", unit: "mm", scale: 1e3 },
  "regen.channels.min_channel_width": { label: "Minimum channel width", unit: "mm", scale: 1e3 },
  "regen.solver.coolant": { label: "Coolant" },
  "regen.solver.coolant_side": { label: "Cooling with" },
  "regen.solver.inlet.pressure_bar": { label: "Coolant inlet pressure", unit: "bar" },
  "regen.solver.inlet.temperature_K": { label: "Coolant inlet temperature", unit: "K" },
  "regen.solver.inlet.location": { label: "Coolant flow direction" },
  "regen.solver.wall.material": { label: "Wall material" },
  "regen.solver.wall.max_wall_temp_K": { label: "Wall temperature limit", unit: "K" },
  "regen.solver.roughness": { label: "Wall roughness", unit: "µm", scale: 1e6 },
  "regen.solver.coolant_correlation": { label: "Coolant heat-transfer model" },
  "regen.solver.coolant_fraction": { label: "Share of propellant flow used" },
  "regen.geometry.n_stations": { label: "Solver stations" },
  "regen.solver.skirt.enabled": { label: "Radiation-cooled extension" },
  "regen.solver.skirt.emissivity": { label: "Extension emissivity" },
  "film_cooling.fraction": { label: "Film share of total flow", unit: "%", scale: 100 },
  "film_cooling.side": { label: "Film propellant" },
  "film_cooling.effectiveness_length_m": { label: "Film decay length", unit: "mm", scale: 1e3 },
  "film_cooling.film_temp_K": { label: "Film temperature", unit: "K" },
};

/** Friendly label for any config path (falls back to a readable version of the key). */
export function labelFor(path: string): string {
  if (FIELDS[path]) return FIELDS[path].label;
  const trimmed = path.replace(/\.\d+(\.\d+)?$/, "");
  if (FIELDS[trimmed]) return `${FIELDS[trimmed].label} (profile)`;
  const last = path.split(".").filter((s) => !/^\d+$/.test(s)).pop() ?? path;
  return last.replace(/_(m|K|bar|N|deg|kg_s|pa_s)$/i, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function formatConfigValue(path: string, v: Json): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "on" : "off";
  if (Array.isArray(v) || typeof v === "object") return Array.isArray(v) ? `${v.length} points` : "…";
  const info = FIELDS[path];
  if (typeof v === "number" && info) {
    const x = v * (info.scale ?? 1);
    const s = Math.abs(x) >= 1000 ? x.toFixed(0) : Number(x.toPrecision(4)).toString();
    return info.unit ? `${s} ${info.unit}` : s;
  }
  return String(v);
}

// ─── diff ─────────────────────────────────────────────────────────────────
export function flatten(obj: Json, prefix = "", out: Record<string, Json> = {}): Record<string, Json> {
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj)) flatten(v, prefix ? `${prefix}.${k}` : k, out);
  } else {
    out[prefix] = obj;
  }
  return out;
}

export interface Change { path: string; label: string; before: string; after: string }

export function diffDesigns(a: Design, b: Design): Change[] {
  const fa = flatten(a), fb = flatten(b);
  const keys = [...new Set([...Object.keys(fa), ...Object.keys(fb)])].filter((k) => k !== "config_hash");
  const out: Change[] = [];
  for (const k of keys.sort()) {
    const va = fa[k], vb = fb[k];
    if (JSON.stringify(va ?? null) === JSON.stringify(vb ?? null)) continue;
    if (k.startsWith("regen.export") || k.startsWith("regen.meta")) continue;
    out.push({ path: k, label: labelFor(k), before: formatConfigValue(k, va), after: formatConfigValue(k, vb) });
  }
  return out;
}

// ─── KPIs captured with each version ──────────────────────────────────────
export interface Kpis {
  thrust_N?: number; isp_s?: number; isp_vac_s?: number; pc_bar?: number; of_ratio?: number;
  mdot_kg_s?: number; throat_d_mm?: number; exit_d_mm?: number; length_mm?: number;
  q_max_MW_m2?: number; heat_load_kW?: number; T_wall_max_K?: number; wall_margin_K?: number;
  dp_bar?: number; outlet_T_K?: number; warnings?: number;
}

export function collectKpis(perf: PerformanceResult | null, heat: HeatFluxResult | null, cool: CoolingResult | null): Kpis {
  const k: Kpis = {};
  if (perf) {
    const p = perf.performance, g = perf.geometry;
    Object.assign(k, {
      thrust_N: p.thrust_N, isp_s: p.isp_s, isp_vac_s: p.isp_vac_s, pc_bar: p.pc_bar, of_ratio: p.of_ratio,
      mdot_kg_s: p.mdot_total_kg_s, throat_d_mm: g.throat_diameter_m * 1e3, exit_d_mm: g.exit_diameter_m * 1e3,
      length_mm: g.total_length_m * 1e3, warnings: perf.warnings.length,
    });
  }
  if (heat) Object.assign(k, { q_max_MW_m2: heat.summary.q_max_W_m2 / 1e6, heat_load_kW: heat.summary.Q_total_W / 1e3 });
  if (cool?.ok) {
    const s = cool.summary;
    Object.assign(k, { T_wall_max_K: s.T_wall_max_K, wall_margin_K: s.wall_margin_K, dp_bar: s.dp_bar, outlet_T_K: s.outlet_T_K });
  }
  for (const key of Object.keys(k) as (keyof Kpis)[]) {
    const v = k[key];
    if (typeof v === "number") k[key] = Number(v.toPrecision(5));
    if (v === undefined || v === null) delete k[key];
  }
  return k;
}

export const KPI_META: Record<keyof Kpis, { label: string; unit: string; better?: "up" | "down"; digits: number }> = {
  thrust_N: { label: "Thrust", unit: "N", digits: 0 },
  isp_s: { label: "Isp", unit: "s", better: "up", digits: 1 },
  isp_vac_s: { label: "Isp vac", unit: "s", better: "up", digits: 1 },
  pc_bar: { label: "Pc", unit: "bar", digits: 1 },
  of_ratio: { label: "O/F", unit: "", digits: 2 },
  mdot_kg_s: { label: "Flow", unit: "kg/s", digits: 3 },
  throat_d_mm: { label: "Throat Ø", unit: "mm", digits: 2 },
  exit_d_mm: { label: "Exit Ø", unit: "mm", digits: 1 },
  length_mm: { label: "Length", unit: "mm", digits: 0 },
  q_max_MW_m2: { label: "Peak flux", unit: "MW/m²", better: "down", digits: 1 },
  heat_load_kW: { label: "Heat load", unit: "kW", better: "down", digits: 1 },
  T_wall_max_K: { label: "Wall max", unit: "K", better: "down", digits: 0 },
  wall_margin_K: { label: "Margin", unit: "K", better: "up", digits: 0 },
  dp_bar: { label: "Δp", unit: "bar", better: "down", digits: 2 },
  outlet_T_K: { label: "Coolant out", unit: "K", digits: 0 },
  warnings: { label: "Warnings", unit: "", better: "down", digits: 0 },
};
