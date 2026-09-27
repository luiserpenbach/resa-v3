// HTTP helpers + typed calculation API (/api/calc/*).

export type Json = any; // eslint-disable-line @typescript-eslint/no-explicit-any
export type Design = Record<string, Json>;

export interface FieldError {
  path: (string | number)[];
  message: string;
}

export class ApiError extends Error {
  status: number;
  detail: Json;
  constructor(status: number, detail: Json) {
    super(typeof detail === "string" ? detail : detail?.message ?? `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
  get fieldErrors(): FieldError[] {
    return Array.isArray(this.detail) ? (this.detail as FieldError[]) : [];
  }
}

export async function request<T>(method: string, url: string, body?: Json, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "Cannot reach the RESA server — is it running?");
  }
  if (!res.ok) {
    let detail: Json = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail ?? j;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("json") ? res.json() : res.blob()) as Promise<T>;
}

export const get = <T>(url: string, signal?: AbortSignal) => request<T>("GET", url, undefined, signal);
export const post = <T>(url: string, body: Json, signal?: AbortSignal) => request<T>("POST", url, body, signal);

// ─── calculation payloads ────────────────────────────────────────────────
export interface Warning {
  area: "performance" | "nozzle" | "chamber" | "cooling" | "propellants";
  message: string;
}

export interface PerformanceResult {
  ok: true;
  engine: string;
  mode: "design" | "analyze";
  performance: {
    thrust_N: number; isp_s: number; isp_vac_s?: number; pc_bar: number; of_ratio: number; eps: number;
    pe_bar: number; cf: number; exit_mach: number; mdot_total_kg_s: number; mdot_ox_kg_s: number;
    mdot_fuel_kg_s: number; cstar_m_s: number; cstar_ideal_m_s: number; eta_cstar: number; eta_cf: number;
    tc_K: number; gamma: number; mw_kg_kmol: number; separated: boolean; isp_vac_ideal_s?: number;
    p_amb_bar: number;
    band?: { eta_tol: number; isp_lo_s: number; isp_hi_s: number; pc_lo_bar: number; pc_hi_bar: number };
    nozzle_models?: Record<string, number | string | null>;
    losses?: { re_throat: number; eta_cf_estimate: number; divergence_efficiency: number; bl_loss_fraction: number };
    coupling?: { iterations: number; converged: boolean; fuel_temp_K: number; ox_temp_K: number; regen_outlet_T_K: number | null; side: string | null };
    film?: Record<string, number | string>;
  };
  geometry: {
    throat_diameter_m: number; exit_diameter_m: number; chamber_diameter_m: number; chamber_length_m: number;
    convergent_length_m: number; cylinder_length_m: number; nozzle_length_m: number; total_length_m: number;
    contraction_ratio: number; eps: number; theta_n_deg: number; theta_e_deg: number;
    chamber_volume_m3: number; l_star_m: number; contour_method: string;
  };
  contour: { x_m: number[]; r_m: number[] };
  propellant_states: { oxidizer: string; fuel: string; chemistry: string; nozzle_flow: string };
  provenance: Record<string, string>;
  warnings: Warning[];
  elapsed_s: number;
}

export interface CoolantCapacity {
  side: "fuel" | "oxidizer"; fluid: string; mdot_kg_s: number; inlet_T_K: number; pressure_bar: number;
  outlet_T_K: number | null; dh_kJ_kg: number; t_sat_K: number | null; boils: boolean; note: string;
}

export interface HeatFluxResult {
  ok: true;
  wall_temp_K: number;
  profiles: {
    x_m: number[]; r_m: number[]; mach: number[]; t_aw_K: number[]; h_g_W_m2K: number[]; q_W_m2: number[];
    q_lo_W_m2: number[] | null; q_hi_W_m2: number[] | null;
  };
  summary: {
    q_max_W_m2: number; x_q_max_m: number; q_throat_W_m2: number; Q_total_W: number; Q_chamber_W: number;
    Q_nozzle_W: number; wetted_area_m2: number; t_aw_throat_K: number; bartz_correction: number;
    bartz_correction_tol: number | null;
  };
  coolant_capacity: CoolantCapacity[];
  property_note: string;
}

export interface PhData {
  fluid: string; p_crit_bar: number; T_crit_K: number; h_crit_kJ_kg: number | null;
  dome: { h_liquid_kJ_kg: number[]; p_liquid_bar: number[]; h_vapor_kJ_kg: number[]; p_vapor_bar: number[] };
  isotherms: { T_K: number; h_kJ_kg: number[]; p_bar: number[] }[];
  error?: string;
}

export interface CoolingResult {
  ok: boolean;
  error?: string;
  fidelity: "preview" | "full";
  summary: Record<string, Json>;
  profiles: Record<string, (number | null)[]>;
  path: { x_m: number[]; h_kJ_kg: number[]; p_bar: number[]; T_K: number[] };
  ph: PhData;
  wall_limit_K: number;
  warnings: Warning[];
  band?: { tol: number; lo: Record<string, number>; hi: Record<string, number> };
  skirt?: { x_m: number[]; T_wall_K: number[]; limit_K: number | null; material: string };
  elapsed_s: number;
}

export interface GeometryResult {
  ok: true;
  section: {
    x_m: number; x_range: [number, number]; x_throat_m: number;
    station: { r_m: number; n_channels: number; channel_width_m: number; channel_height_m: number;
      rib_width_m: number; wall_thickness_m: number; beta_deg: number; pitch_perp_m: number };
    profiles: { x_m: number[]; height_m: number[]; rib_width_m: number[]; wall_thickness_m: number[];
      channel_width_m: number[]; beta_deg: number[] };
  };
  assembly: {
    n_channels: number; n_stations: number; helical: boolean; closeout_thickness_m: number;
    profile: { x_m: number[]; r_inner_m: number[]; r_floor_m: number[]; r_top_m: number[]; r_outer_m: number[] };
    channel: { floor_L: number[][]; floor_R: number[][]; top_L: number[][]; top_R: number[][] };
  };
}

export interface Sweep {
  kind: string; mdot_ox_kg_s: number[]; mdot_fuel_kg_s: number[]; mdot_total_kg_s: number[]; of: number[];
  pc_bar: number[]; thrust_N: number[]; isp_s: number[]; cf: number[]; cstar_eff_m_s: number[];
  pe_bar: number[]; separated: boolean[];
}

export interface OffdesignResult {
  ok: boolean;
  error?: string;
  offdesign: {
    notes: string[]; ox_throttle?: Sweep; of_sweep?: Sweep;
    envelope?: { throttle_frac: number[]; of: number[]; pc_bar: number[][]; thrust_N: number[][]; isp_s: number[][]; separated: boolean[][] };
  };
  nominal: { thrust_N: number; of_ratio: number; isp_s: number; pc_bar: number };
  elapsed_s: number;
}

export interface TradeResult {
  ok: true; parameter: string; label: string; unit: string; elapsed_s: number;
  rows: ({ value: number; ok: boolean; error?: string } & Record<string, number | boolean | string | null>)[];
}

export interface Catalog {
  propellants: { id: string; label: string; role: "oxidizer" | "fuel"; fluid: string | null; cea_name: string;
    phase: "liquid" | "gas"; temperature_K: number; can_cool: boolean }[];
  materials: { key: string; name: string; max_service_T_K: number; k_300K_W_mK: number; yield_300K_MPa: number; note: string }[];
  chemistry: { cea: boolean; rocketcea: boolean };
  trade_parameters: { path: string; label: string; unit: string }[];
}

export const calc = {
  catalog: () => get<Catalog>("/api/calc/catalog"),
  validate: (design: Design, signal?: AbortSignal) =>
    post<{ ok: boolean; errors: FieldError[]; mode?: string }>("/api/calc/validate", { design }, signal),
  performance: (design: Design, signal?: AbortSignal) =>
    post<PerformanceResult>("/api/calc/performance", { design }, signal),
  heatFlux: (design: Design, wall_temp_K: number, signal?: AbortSignal) =>
    post<HeatFluxResult>("/api/calc/heat-flux", { design, wall_temp_K }, signal),
  cooling: (design: Design, fidelity: "preview" | "full", signal?: AbortSignal) =>
    post<CoolingResult>("/api/calc/cooling", { design, fidelity }, signal),
  geometry: (design: Design, x_m: number | null, signal?: AbortSignal) =>
    post<GeometryResult>("/api/calc/cooling/geometry", { design, x_m }, signal),
  offdesign: (design: Design, signal?: AbortSignal) =>
    post<OffdesignResult>("/api/calc/offdesign", { design }, signal),
  trade: (design: Design, parameter: string, values: number[], include: string[], signal?: AbortSignal) =>
    post<TradeResult>("/api/calc/trade-study", { design, parameter, values, include }, signal),
  suggestChannels: (design: Design, signal?: AbortSignal) =>
    post<{ ok: true; side: "fuel" | "oxidizer"; coolant: string; count: number; height_m: number | number[][]; height_throat_m: number; rib_m: number; wall_m: number;
      inlet_p_bar: number; inlet_T_K: number; material: string; channel_width_m: number; target_velocity_m_s: number;
      q_max_W_m2: number; notes: string[]; regen: Design; trials: Record<string, unknown>[] }>("/api/calc/cooling/suggest", { design }, signal),
  exportChannel: (design: Design, format: "stl" | "step", channel_id = 0) =>
    post<Blob>("/api/calc/cooling/export", { design, format, channel_id }),
};

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function downloadText(text: string, filename: string, type = "text/plain") {
  downloadBlob(new Blob([text], { type }), filename);
}

export const yaml = {
  parse: (text: string) => post<{ design: Design; valid: boolean; errors: FieldError[] }>("/api/calc/yaml/parse", { text }),
  dump: (design: Design) => post<{ text: string }>("/api/calc/yaml/dump", { design }),
};
