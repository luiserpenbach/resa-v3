// Project workspace client. Two interchangeable backends:
//   RemoteWorkspace  — the server store (workspace/ folder or a database)
//   BrowserWorkspace — this browser's storage, for hosted deployments without
//                      a database; projects move between the two as bundles.
import { ApiError, Design, Json, get, request } from "./api";

export type DesignStatus = "concept" | "preliminary" | "detailed" | "frozen";

export interface Project {
  id: string; name: string; description: string; created_at: string; created_by: string;
  updated_at: string; design_count: number;
}
export interface DerivedFrom { design_id: string; design_name: string; version: number | null }
export interface DesignSummary {
  id: string; project_id: string; name: string; description: string; status: DesignStatus;
  revision: number; head_version: number | null; has_unsaved_changes: boolean; updated_at: string;
  updated_by: string; created_at?: string; created_by?: string; derived_from: DerivedFrom | null;
  is_baseline: boolean; kpis: Record<string, Json>;
}
export interface DesignFull extends DesignSummary { config: Design }
export interface VersionSummary { number: number; message: string; author: string; created_at: string; kpis: Record<string, Json> }
export interface Version extends VersionSummary { config: Design }
export interface Bundle {
  format: "resa-project"; format_version: 1; exported_at: string;
  project: { name: string; description: string; created_at?: string; created_by?: string };
  designs: { id: string; name: string; description: string; status: DesignStatus; is_baseline: boolean;
    derived_from: DerivedFrom | null; config: Design; versions: Version[] }[];
}
export interface WorkspaceInfo { storage: "files" | "database" | "none" | "browser"; writable: boolean; location: string; examples_available: boolean }

export interface Workspace {
  readonly kind: "server" | "browser";
  info(): Promise<WorkspaceInfo>;
  listProjects(): Promise<Project[]>;
  createProject(name: string, description: string, author: string): Promise<Project>;
  getProject(pid: string): Promise<{ project: Project; designs: DesignSummary[] }>;
  updateProject(pid: string, patch: { name?: string; description?: string }): Promise<Project>;
  deleteProject(pid: string): Promise<void>;
  createDesign(pid: string, body: { name: string; description?: string; config?: Design | null; author: string;
    derived_from?: { design_id: string; version?: number | null } | null }): Promise<DesignFull>;
  getDesign(pid: string, did: string): Promise<DesignFull>;
  updateDesign(pid: string, did: string, patch: { name?: string; description?: string; status?: DesignStatus;
    is_baseline?: boolean; author?: string }): Promise<DesignSummary>;
  saveDraft(pid: string, did: string, config: Design, revision: number, author: string):
    Promise<{ revision: number; updated_at: string; has_unsaved_changes: boolean }>;
  deleteDesign(pid: string, did: string): Promise<void>;
  listVersions(pid: string, did: string): Promise<VersionSummary[]>;
  createVersion(pid: string, did: string, message: string, author: string, kpis: Record<string, Json>): Promise<VersionSummary>;
  getVersion(pid: string, did: string, n: number): Promise<Version>;
  restoreVersion(pid: string, did: string, n: number, author: string): Promise<DesignFull>;
  exportProject(pid: string): Promise<Bundle>;
  importBundle(bundle: Bundle, author: string): Promise<Project>;
  importExamples(author: string): Promise<Project[]>;
}

export class ConflictError extends Error {
  currentRevision: number;
  constructor(currentRevision: number) {
    super("Someone else saved this design in the meantime.");
    this.currentRevision = currentRevision;
  }
}

// ─── server ───────────────────────────────────────────────────────────────
const W = "/api/workspace";
const enc = encodeURIComponent;

export class RemoteWorkspace implements Workspace {
  readonly kind = "server" as const;
  info() { return get<WorkspaceInfo>(`${W}/info`); }
  listProjects() { return get<Project[]>(`${W}/projects`); }
  createProject(name: string, description: string, author: string) {
    return request<Project>("POST", `${W}/projects`, { name, description, author });
  }
  getProject(pid: string) { return get<{ project: Project; designs: DesignSummary[] }>(`${W}/projects/${enc(pid)}`); }
  updateProject(pid: string, patch: { name?: string; description?: string }) {
    return request<Project>("PATCH", `${W}/projects/${enc(pid)}`, patch);
  }
  async deleteProject(pid: string) { await request("DELETE", `${W}/projects/${enc(pid)}`); }
  createDesign(pid: string, body: Json) { return request<DesignFull>("POST", `${W}/projects/${enc(pid)}/designs`, body); }
  getDesign(pid: string, did: string) { return get<DesignFull>(`${W}/projects/${enc(pid)}/designs/${enc(did)}`); }
  updateDesign(pid: string, did: string, patch: Json) {
    return request<DesignSummary>("PATCH", `${W}/projects/${enc(pid)}/designs/${enc(did)}`, patch);
  }
  async saveDraft(pid: string, did: string, config: Design, revision: number, author: string) {
    try {
      return await request<{ revision: number; updated_at: string; has_unsaved_changes: boolean }>(
        "PUT", `${W}/projects/${enc(pid)}/designs/${enc(did)}/draft`, { config, revision, author });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) throw new ConflictError(e.detail?.current_revision ?? -1);
      throw e;
    }
  }
  async deleteDesign(pid: string, did: string) { await request("DELETE", `${W}/projects/${enc(pid)}/designs/${enc(did)}`); }
  listVersions(pid: string, did: string) { return get<VersionSummary[]>(`${W}/projects/${enc(pid)}/designs/${enc(did)}/versions`); }
  createVersion(pid: string, did: string, message: string, author: string, kpis: Record<string, Json>) {
    return request<VersionSummary>("POST", `${W}/projects/${enc(pid)}/designs/${enc(did)}/versions`, { message, author, kpis });
  }
  getVersion(pid: string, did: string, n: number) { return get<Version>(`${W}/projects/${enc(pid)}/designs/${enc(did)}/versions/${n}`); }
  restoreVersion(pid: string, did: string, n: number, author: string) {
    return request<DesignFull>("POST", `${W}/projects/${enc(pid)}/designs/${enc(did)}/versions/${n}/restore`, { author });
  }
  exportProject(pid: string) { return get<Bundle>(`${W}/projects/${enc(pid)}/export`); }
  importBundle(bundle: Bundle, author: string) { return request<Project>("POST", `${W}/import`, { bundle, author }); }
  importExamples(author: string) { return request<Project[]>("POST", `${W}/examples`, { author }); }
}

// ─── browser storage ──────────────────────────────────────────────────────
interface LocalDesign {
  meta: Omit<DesignSummary, "has_unsaved_changes" | "kpis" | "head_version" | "project_id">;
  config: Design;
  versions: Version[];
}
interface LocalProject { project: Omit<Project, "design_count" | "updated_at"> & { updated_at: string }; designs: Record<string, LocalDesign> }
interface LocalState { projects: Record<string, LocalProject> }

const KEY = "resa.workspace.v1";
const now = () => new Date().toISOString();
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v));

export function slugify(name: string): string {
  const s = name.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48).replace(/-+$/g, "");
  return s || "untitled";
}
function uniqueId(base: string, taken: Iterable<string>): string {
  const set = new Set(taken);
  if (!set.has(base)) return base;
  for (let i = 2; ; i++) if (!set.has(`${base}-${i}`)) return `${base}-${i}`;
}
function notFound(what: string): never { throw new ApiError(404, `${what} not found`); }
const sameConfig = (a: Design, b: Design) => JSON.stringify(a) === JSON.stringify(b);

export class BrowserWorkspace implements Workspace {
  readonly kind = "browser" as const;

  private load(): LocalState {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) return JSON.parse(raw) as LocalState;
    } catch { /* storage blocked or corrupt */ }
    return { projects: {} };
  }
  private save(s: LocalState) {
    try {
      localStorage.setItem(KEY, JSON.stringify(s));
    } catch {
      throw new ApiError(507, "This browser's storage is full or blocked — export projects to keep them.");
    }
  }
  private proj(s: LocalState, pid: string) { return s.projects[pid] ?? notFound("project"); }
  private des(s: LocalState, pid: string, did: string) { return this.proj(s, pid).designs[did] ?? notFound("design"); }

  private summary(pid: string, d: LocalDesign): DesignSummary {
    const head = d.versions[d.versions.length - 1];
    return {
      ...clone(d.meta), project_id: pid, head_version: head ? head.number : null,
      has_unsaved_changes: !head || !sameConfig(head.config, d.config), kpis: head ? clone(head.kpis) : {},
    };
  }
  private projectOut(p: LocalProject): Project {
    const times = [p.project.updated_at, ...Object.values(p.designs).map((d) => d.meta.updated_at)];
    return { ...clone(p.project), updated_at: times.sort().at(-1)!, design_count: Object.keys(p.designs).length };
  }

  async info(): Promise<WorkspaceInfo> {
    return { storage: "browser", writable: true, location: "this browser", examples_available: true };
  }
  async listProjects() {
    return Object.values(this.load().projects).map((p) => this.projectOut(p))
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }
  async createProject(name: string, description: string, author: string) {
    const s = this.load();
    const id = uniqueId(slugify(name), Object.keys(s.projects));
    const t = now();
    s.projects[id] = { project: { id, name, description, created_at: t, created_by: author, updated_at: t }, designs: {} };
    this.save(s);
    return this.projectOut(s.projects[id]);
  }
  async getProject(pid: string) {
    const p = this.proj(this.load(), pid);
    const designs = Object.values(p.designs).map((d) => this.summary(pid, d))
      .sort((a, b) => Number(b.is_baseline) - Number(a.is_baseline) || a.name.localeCompare(b.name));
    return { project: this.projectOut(p), designs };
  }
  async updateProject(pid: string, patch: { name?: string; description?: string }) {
    const s = this.load();
    const p = this.proj(s, pid);
    Object.assign(p.project, Object.fromEntries(Object.entries(patch).filter(([, v]) => v != null)), { updated_at: now() });
    this.save(s);
    return this.projectOut(p);
  }
  async deleteProject(pid: string) {
    const s = this.load();
    this.proj(s, pid);
    delete s.projects[pid];
    this.save(s);
  }
  async createDesign(pid: string, body: { name: string; description?: string; config?: Design | null; author: string;
    derived_from?: { design_id: string; version?: number | null } | null }) {
    const s = this.load();
    const p = this.proj(s, pid);
    let config = body.config ?? null;
    let derived: DerivedFrom | null = null;
    if (body.derived_from) {
      const src = p.designs[body.derived_from.design_id] ?? notFound("source design");
      const v = body.derived_from.version;
      if (!config) {
        config = v ? (src.versions.find((x) => x.number === v) ?? notFound("version")).config : src.config;
      }
      derived = { design_id: src.meta.id, design_name: src.meta.name, version: v ?? null };
    }
    if (!config) throw new ApiError(422, "a new design needs a config or derived_from");
    const id = uniqueId(slugify(body.name), Object.keys(p.designs));
    const t = now();
    p.designs[id] = {
      meta: { id, name: body.name, description: body.description ?? "", status: "concept", revision: 1,
        updated_at: t, updated_by: body.author, created_at: t, created_by: body.author, derived_from: derived, is_baseline: false },
      config: clone(config), versions: [],
    };
    this.save(s);
    return { ...this.summary(pid, p.designs[id]), config: clone(config) };
  }
  async getDesign(pid: string, did: string) {
    const d = this.des(this.load(), pid, did);
    return { ...this.summary(pid, d), config: clone(d.config) };
  }
  async updateDesign(pid: string, did: string, patch: { name?: string; description?: string; status?: DesignStatus;
    is_baseline?: boolean; author?: string }) {
    const s = this.load();
    const p = this.proj(s, pid);
    const d = this.des(s, pid, did);
    if (patch.is_baseline) Object.values(p.designs).forEach((x) => (x.meta.is_baseline = false));
    for (const k of ["name", "description", "status", "is_baseline"] as const) {
      if (patch[k] !== undefined) (d.meta as Json)[k] = patch[k];
    }
    d.meta.updated_at = now();
    if (patch.author) d.meta.updated_by = patch.author;
    this.save(s);
    return this.summary(pid, d);
  }
  async saveDraft(pid: string, did: string, config: Design, revision: number, author: string) {
    const s = this.load();
    const d = this.des(s, pid, did);
    if (d.meta.revision !== revision) throw new ConflictError(d.meta.revision);
    d.config = clone(config);
    d.meta.revision += 1;
    d.meta.updated_at = now();
    d.meta.updated_by = author;
    this.save(s);
    return { revision: d.meta.revision, updated_at: d.meta.updated_at, has_unsaved_changes: this.summary(pid, d).has_unsaved_changes };
  }
  async deleteDesign(pid: string, did: string) {
    const s = this.load();
    this.des(s, pid, did);
    delete s.projects[pid].designs[did];
    this.save(s);
  }
  async listVersions(pid: string, did: string) {
    return this.des(this.load(), pid, did).versions.map(({ config: _c, ...v }) => clone(v)).reverse();
  }
  async createVersion(pid: string, did: string, message: string, author: string, kpis: Record<string, Json>) {
    const s = this.load();
    const d = this.des(s, pid, did);
    const v: Version = { number: (d.versions.at(-1)?.number ?? 0) + 1, message, author, created_at: now(),
      kpis: clone(kpis), config: clone(d.config) };
    d.versions.push(v);
    d.meta.updated_at = v.created_at;
    d.meta.updated_by = author;
    this.save(s);
    const { config: _c, ...out } = v;
    return out;
  }
  async getVersion(pid: string, did: string, n: number) {
    const v = this.des(this.load(), pid, did).versions.find((x) => x.number === n) ?? notFound("version");
    return clone(v);
  }
  async restoreVersion(pid: string, did: string, n: number, author: string) {
    const s = this.load();
    const d = this.des(s, pid, did);
    const v = d.versions.find((x) => x.number === n) ?? notFound("version");
    d.config = clone(v.config);
    d.meta.revision += 1;
    d.meta.updated_at = now();
    d.meta.updated_by = author;
    this.save(s);
    return { ...this.summary(pid, d), config: clone(d.config) };
  }
  async exportProject(pid: string): Promise<Bundle> {
    const p = this.proj(this.load(), pid);
    return {
      format: "resa-project", format_version: 1, exported_at: now(),
      project: { name: p.project.name, description: p.project.description, created_at: p.project.created_at, created_by: p.project.created_by },
      designs: Object.values(p.designs).map((d) => ({
        id: d.meta.id, name: d.meta.name, description: d.meta.description, status: d.meta.status,
        is_baseline: d.meta.is_baseline, derived_from: d.meta.derived_from, config: clone(d.config), versions: clone(d.versions),
      })),
    };
  }
  async importBundle(bundle: Bundle, author: string) {
    // same checks and normalisation as the server (store.validate_bundle)
    if (bundle?.format !== "resa-project" || bundle.format_version !== 1 || !Array.isArray(bundle.designs)
        || !bundle.project || typeof bundle.project.name !== "string" || !bundle.project.name.trim()) {
      throw new ApiError(422, "not a RESA project file (format resa-project, version 1)");
    }
    const s = this.load();
    const id = uniqueId(slugify(bundle.project.name), Object.keys(s.projects));
    const t = now();
    const lp: LocalProject = {
      project: { id, name: bundle.project.name.trim().slice(0, 120), description: bundle.project.description ?? "",
        created_at: t, created_by: author, updated_at: t },
      designs: {},
    };
    const idMap = new Map<string, string>();
    for (const d of bundle.designs) {
      if (!d || typeof d.name !== "string" || !d.name.trim() || typeof d.config !== "object" || !d.config) {
        throw new ApiError(422, "project file contains a design without a name or configuration");
      }
      const validId = typeof d.id === "string" && /^[a-z0-9][a-z0-9-]{0,63}$/.test(d.id);
      const did = uniqueId(validId ? d.id : slugify(d.name), Object.keys(lp.designs));
      if (typeof d.id === "string") idMap.set(d.id, did);
      const versions = [...(d.versions ?? [])].sort((a, b) => a.number - b.number);
      if (new Set(versions.map((v) => v.number)).size !== versions.length) {
        throw new ApiError(422, `design “${d.name}” has duplicate version numbers`);
      }
      lp.designs[did] = {
        meta: { id: did, name: d.name.trim().slice(0, 120), description: d.description ?? "", status: d.status ?? "concept",
          revision: 1, updated_at: t, updated_by: author, created_at: t, created_by: author,
          derived_from: d.derived_from ?? null, is_baseline: false },
        config: clone(d.config), versions: clone(versions),
      };
    }
    // references between designs follow renamed ids; at most one baseline
    let baselineTaken = false;
    for (const [i, d] of bundle.designs.entries()) {
      const meta = Object.values(lp.designs)[i].meta;
      const src = meta.derived_from;
      if (src) meta.derived_from = { ...src, design_id: idMap.get(src.design_id) ?? src.design_id };
      if (d.is_baseline && !baselineTaken) { meta.is_baseline = true; baselineTaken = true; }
    }
    s.projects[id] = lp;
    this.save(s);
    return this.projectOut(lp);
  }
  async importExamples(author: string) {
    const bundles = await get<Bundle[]>(`${W}/examples/bundles`);
    const have = new Set((await this.listProjects()).map((p) => p.name.toLowerCase()));
    const out: Project[] = [];
    for (const b of bundles) {
      if (have.has(b.project.name.toLowerCase())) continue;
      out.push(await this.importBundle(b, author));
    }
    return out;
  }
}

let active: Workspace | null = null;
let activeInfo: WorkspaceInfo | null = null;

/** Server store when the server has one, else this browser's storage. */
export async function connectWorkspace(): Promise<{ ws: Workspace; info: WorkspaceInfo }> {
  if (active && activeInfo) return { ws: active, info: activeInfo };
  const remote = new RemoteWorkspace();
  // Only an explicit "no server storage" answer switches to browser storage; a
  // network error or cold-start failure must not silently fork the workspace.
  let info: WorkspaceInfo | null = null;
  let lastError: unknown = null;
  for (let attempt = 0; attempt < 3 && !info; attempt++) {
    try { info = await remote.info(); }
    catch (e) { lastError = e; await new Promise((r) => setTimeout(r, 600 * (attempt + 1))); }
  }
  if (!info) throw lastError instanceof Error ? lastError : new Error("Cannot reach the RESA server");
  if (info.storage === "none") {
    active = new BrowserWorkspace();
    activeInfo = await active.info();
  } else {
    active = remote;
    activeInfo = info;
  }
  return { ws: active, info: activeInfo };
}

export function workspaceSync(): Workspace | null { return active; }
