// Design session: the open engine design, its live results, autosave and
// undo history. Every edit re-validates and recomputes what the visible
// section needs (debounced); drafts autosave to the workspace.
import { create } from "zustand";
import {
  ApiError, CoolingResult, Design, FieldError, GeometryResult, HeatFluxResult, OffdesignResult,
  PerformanceResult, TradeResult, calc,
} from "./api";
import { Kpis, Path, clone, collectKpis, getPath, setPath } from "./design";
import { authorName, toast } from "./stores";
import { ConflictError, DesignFull, VersionSummary, Workspace, connectWorkspace } from "./workspace";

export type Section = "performance" | "chamber" | "heat" | "cooling" | "range" | "trade" | "summary";

export interface Slot<T> { data: T | null; loading: boolean; error: string | null; stale: boolean }
const empty = <T,>(): Slot<T> => ({ data: null, loading: false, error: null, stale: false });

export type Source = { kind: "project"; pid: string; did: string } | { kind: "scratch" };
export type SaveState = "saved" | "dirty" | "saving" | "error" | "conflict";

interface SessionState {
  source: Source | null;
  meta: Omit<DesignFull, "config"> | null;
  projectName: string;
  config: Design | null;
  loadError: string | null;
  saveState: SaveState;
  errors: FieldError[];
  section: Section;
  wallTemp: number;
  fidelity: "preview" | "full";
  perf: Slot<PerformanceResult>;
  heat: Slot<HeatFluxResult>;
  cool: Slot<CoolingResult>;
  geo: Slot<GeometryResult>;
  range: Slot<OffdesignResult>;
  trade: Slot<TradeResult>;
  versions: VersionSummary[];
  coolingNotes: string[];
  canUndo: boolean;
  canRedo: boolean;

  open(source: Source): Promise<void>;
  close(): void;
  setSection(s: Section): void;
  update(path: Path, value: unknown): void;
  replace(config: Design, label?: string): void;
  undo(): void;
  redo(): void;
  setWallTemp(t: number): void;
  setFidelity(f: "preview" | "full"): void;
  recompute(force?: boolean): void;
  runRange(): Promise<void>;
  runTrade(parameter: string, values: number[], include: string[]): Promise<void>;
  loadGeometry(x_m?: number | null): Promise<void>;
  flush(): Promise<void>;
  saveVersion(message: string): Promise<void>;
  restore(n: number): Promise<void>;
  refreshVersions(): Promise<void>;
  patchMeta(patch: Parameters<Workspace["updateDesign"]>[2]): Promise<void>;
  setCoolingNotes(notes: string[]): void;
  kpis(): Kpis;
}

const SCRATCH_KEY = "resa.scratch.v1";
const CALC_DELAY = 350;
const SAVE_DELAY = 1200;

let ws: Workspace | null = null;
let calcTimer: ReturnType<typeof setTimeout> | undefined;
let saveTimer: ReturnType<typeof setTimeout> | undefined;
let savePromise: Promise<void> | null = null;
const controllers: Partial<Record<string, AbortController>> = {};
let past: Design[] = [];
let future: Design[] = [];
let lastEdit = { key: "", at: 0 };
let computedKey = "";

function abortable(key: string): AbortSignal {
  controllers[key]?.abort();
  const c = new AbortController();
  controllers[key] = c;
  return c.signal;
}
const isAbort = (e: unknown) => (e as Error)?.name === "AbortError";
const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function readScratch(): Design | null {
  try {
    const raw = localStorage.getItem(SCRATCH_KEY);
    return raw ? (JSON.parse(raw) as Design) : null;
  } catch { return null; }
}
export function writeScratch(config: Design) {
  try { localStorage.setItem(SCRATCH_KEY, JSON.stringify(config)); } catch { /* blocked */ }
}

export const useSession = create<SessionState>((set, get) => {
  const slot = <K extends "perf" | "heat" | "cool" | "geo" | "range" | "trade">(k: K, patch: Partial<Slot<unknown>>) =>
    set((s) => ({ [k]: { ...s[k], ...patch } }) as Partial<SessionState>);

  function scheduleCalc(delay = CALC_DELAY) {
    clearTimeout(calcTimer);
    calcTimer = setTimeout(() => get().recompute(), delay);
  }

  function scheduleSave() {
    set({ saveState: "dirty" });
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => void get().flush(), SAVE_DELAY);
  }

  function markStale() {
    set((s) => ({
      perf: { ...s.perf, stale: true }, heat: { ...s.heat, stale: true }, cool: { ...s.cool, stale: true },
      geo: { ...s.geo, stale: true }, range: { ...s.range, stale: true },
    }));
  }

  async function runCooling(config: Design) {
    if (!config.regen) { slot("cool", { data: null, loading: false, error: null, stale: false }); return; }
    const signal = abortable("cool");
    slot("cool", { loading: true });
    try {
      const r = await calc.cooling(config, get().fidelity, signal);
      slot("cool", { data: r, loading: false, error: r.ok ? null : r.error ?? "Cooling solve failed", stale: false });
    } catch (e) {
      if (!isAbort(e)) slot("cool", { loading: false, error: msg(e) });
    }
  }

  return {
    source: null, meta: null, projectName: "", config: null, loadError: null, saveState: "saved", errors: [],
    section: "performance", wallTemp: 800, fidelity: "preview",
    perf: empty(), heat: empty(), cool: empty(), geo: empty(), range: empty(), trade: empty(),
    versions: [], coolingNotes: [], canUndo: false, canRedo: false,

    setCoolingNotes(coolingNotes) { set({ coolingNotes }); },

    async open(source) {
      get().close();
      set({ source, loadError: null });
      try {
        if (source.kind === "scratch") {
          const config = readScratch();
          if (!config) throw new Error("No quick estimate yet");
          set({ config, meta: null, projectName: "", saveState: "saved" });
        } else {
          ws = (await connectWorkspace()).ws;
          const [d, p] = await Promise.all([ws.getDesign(source.pid, source.did), ws.getProject(source.pid)]);
          const { config, ...meta } = d;
          set({ config, meta, projectName: p.project.name, saveState: "saved" });
          void get().refreshVersions();
        }
        computedKey = "";
        get().recompute();
      } catch (e) {
        set({ loadError: msg(e) });
      }
    },

    close() {
      clearTimeout(calcTimer);
      if (get().saveState === "dirty") void get().flush();
      clearTimeout(saveTimer);
      Object.values(controllers).forEach((c) => c?.abort());
      past = []; future = []; computedKey = "";
      set({
        source: null, meta: null, config: null, errors: [], versions: [], coolingNotes: [], canUndo: false, canRedo: false,
        perf: empty(), heat: empty(), cool: empty(), geo: empty(), range: empty(), trade: empty(), saveState: "saved",
      });
    },

    setSection(section) {
      const prev = get().section;
      set({ section });
      if (prev !== section) {
        const c = get().config;
        if (!c) return;
        const s = get();
        if ((section === "cooling" || section === "summary") && c.regen && (!s.cool.data || s.cool.stale) && !s.cool.loading) {
          if (get().errors.length === 0) void runCooling(c);
        }
      }
    },

    update(path, value) {
      const cur = get().config;
      if (!cur) return;
      const next = setPath(cur, path, value);
      const key = path.join(".");
      const t = Date.now();
      if (!(key === lastEdit.key && t - lastEdit.at < 900)) {
        past.push(cur);
        if (past.length > 80) past.shift();
      }
      lastEdit = { key, at: t };
      future = [];
      set({ config: next, canUndo: past.length > 0, canRedo: false });
      markStale();
      scheduleCalc();
      if (get().source?.kind === "scratch") writeScratch(next);
      else scheduleSave();
    },

    replace(config) {
      const cur = get().config;
      if (cur) past.push(cur);
      future = [];
      lastEdit = { key: "", at: 0 };
      set({ config, canUndo: past.length > 0, canRedo: false });
      markStale();
      scheduleCalc(50);
      if (get().source?.kind === "scratch") writeScratch(config);
      else scheduleSave();
    },

    undo() {
      const cur = get().config;
      const prev = past.pop();
      if (!cur || !prev) return;
      future.push(cur);
      lastEdit = { key: "", at: 0 };
      set({ config: prev, canUndo: past.length > 0, canRedo: true });
      markStale();
      scheduleCalc(120);
      if (get().source?.kind === "scratch") writeScratch(prev); else scheduleSave();
    },

    redo() {
      const cur = get().config;
      const next = future.pop();
      if (!cur || !next) return;
      past.push(cur);
      set({ config: next, canUndo: true, canRedo: future.length > 0 });
      markStale();
      scheduleCalc(120);
      if (get().source?.kind === "scratch") writeScratch(next); else scheduleSave();
    },

    setWallTemp(t) {
      set({ wallTemp: t });
      set((s) => ({ heat: { ...s.heat, stale: true } }));
      scheduleCalc(200);
    },

    setFidelity(f) {
      set({ fidelity: f });
      const c = get().config;
      if (c?.regen) void runCooling(c);
    },

    recompute(force = false) {
      const config = get().config;
      if (!config) return;
      const s = get();
      const key = JSON.stringify(config) + `|${s.wallTemp}`;
      if (!force && key === computedKey && !s.perf.stale && !s.heat.stale) return;
      computedKey = key;
      const signal = abortable("perf");
      slot("perf", { loading: true });
      slot("heat", { loading: true });
      (async () => {
        try {
          const perf = await calc.performance(config, signal);
          set({ errors: [] });
          slot("perf", { data: perf, loading: false, error: null, stale: false });
          try {
            const heat = await calc.heatFlux(config, get().wallTemp, abortable("heat"));
            slot("heat", { data: heat, loading: false, error: null, stale: false });
          } catch (e) {
            if (!isAbort(e)) slot("heat", { loading: false, error: msg(e) });
          }
          const sec = get().section;
          if (config.regen && (sec === "cooling" || sec === "summary" || get().cool.data)) void runCooling(config);
          if (get().geo.data && config.regen) void get().loadGeometry(get().geo.data?.section.x_m ?? null);
        } catch (e) {
          if (isAbort(e)) return;
          if (e instanceof ApiError && e.status === 422) {
            set({ errors: e.fieldErrors });
            slot("perf", { loading: false, error: null });
            slot("heat", { loading: false });
          } else {
            set({ errors: [] });
            slot("perf", { loading: false, error: msg(e) });
            slot("heat", { loading: false, error: null });
          }
        }
      })();
    },

    async runRange() {
      const config = get().config;
      if (!config) return;
      const signal = abortable("range");
      slot("range", { loading: true, error: null });
      try {
        const r = await calc.offdesign(config, signal);
        slot("range", { data: r, loading: false, error: r.ok ? null : r.error ?? "Failed", stale: false });
      } catch (e) {
        if (!isAbort(e)) slot("range", { loading: false, error: msg(e) });
      }
    },

    async runTrade(parameter, values, include) {
      const config = get().config;
      if (!config) return;
      const signal = abortable("trade");
      slot("trade", { loading: true, error: null });
      try {
        const r = await calc.trade(config, parameter, values, include, signal);
        slot("trade", { data: r, loading: false, error: null, stale: false });
      } catch (e) {
        if (!isAbort(e)) slot("trade", { loading: false, error: msg(e) });
      }
    },

    async loadGeometry(x_m = null) {
      const config = get().config;
      if (!config?.regen) return;
      const signal = abortable("geo");
      slot("geo", { loading: true });
      try {
        const r = await calc.geometry(config, x_m, signal);
        slot("geo", { data: r, loading: false, error: null, stale: false });
      } catch (e) {
        if (!isAbort(e)) slot("geo", { loading: false, error: msg(e) });
      }
    },

    async flush() {
      clearTimeout(saveTimer);
      const s = get();
      if (s.source?.kind !== "project" || !s.meta || !s.config || !ws) return;
      if (s.saveState !== "dirty" && s.saveState !== "error") return;
      if (savePromise) { await savePromise; if (get().saveState !== "dirty") return; }
      const { pid, did } = s.source;
      const config = s.config;
      set({ saveState: "saving" });
      savePromise = (async () => {
        try {
          const r = await ws!.saveDraft(pid, did, config, get().meta!.revision, authorName());
          const stillSame = get().config === config;
          set((st) => ({
            meta: st.meta ? { ...st.meta, revision: r.revision, updated_at: r.updated_at, has_unsaved_changes: r.has_unsaved_changes } : st.meta,
            saveState: stillSame ? "saved" : "dirty",
          }));
          if (!stillSame) scheduleSave();
        } catch (e) {
          if (e instanceof ConflictError) {
            set({ saveState: "conflict" });
            toast("This design was changed elsewhere — reload to see the latest version.", "bad");
          } else {
            set({ saveState: "error" });
            toast(`Could not save: ${msg(e)}`, "bad");
          }
        } finally {
          savePromise = null;
        }
      })();
      await savePromise;
    },

    async saveVersion(message) {
      const s = get();
      if (s.source?.kind !== "project" || !ws) return;
      await get().flush();
      if (get().saveState === "conflict" || get().saveState === "error") throw new Error("Save the working copy first");
      const { pid, did } = s.source;
      const v = await ws.createVersion(pid, did, message, authorName(), get().kpis() as Record<string, unknown>);
      set((st) => ({ meta: st.meta ? { ...st.meta, head_version: v.number, has_unsaved_changes: false, kpis: v.kpis } : st.meta }));
      await get().refreshVersions();
    },

    async restore(n) {
      const s = get();
      if (s.source?.kind !== "project" || !ws) return;
      await get().flush();
      const d = await ws.restoreVersion(s.source.pid, s.source.did, n, authorName());
      const { config, ...meta } = d;
      if (s.config) past.push(s.config);
      set({ config, meta, saveState: "saved", canUndo: past.length > 0 });
      markStale();
      computedKey = "";
      get().recompute();
    },

    async refreshVersions() {
      const s = get();
      if (s.source?.kind !== "project" || !ws) return;
      try {
        set({ versions: await ws.listVersions(s.source.pid, s.source.did) });
      } catch { /* keep list */ }
    },

    async patchMeta(patch) {
      const s = get();
      if (s.source?.kind !== "project" || !ws) return;
      const d = await ws.updateDesign(s.source.pid, s.source.did, { ...patch, author: authorName() });
      set((st) => ({ meta: st.meta ? { ...st.meta, ...d } : st.meta }));
    },

    kpis() {
      const s = get();
      return collectKpis(s.perf.data, s.heat.data, s.config?.regen ? s.cool.data : null);
    },
  };
});

/** Field-level error for a config path (exact match or first nested error). */
export function errorAt(errors: FieldError[], path: Path): string | undefined {
  const key = path.join(".");
  const hit = errors.find((e) => e.path.join(".") === key);
  return hit?.message;
}

export function useValue<T = unknown>(path: Path): T {
  return useSession((s) => getPath(s.config, path)) as T;
}

export { clone };
