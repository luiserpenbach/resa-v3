import { useEffect, useState } from "react";
import { useLocation, useParams } from "wouter";
import { TopBar } from "../App";
import { NewDesignDialog } from "../components/NewDesignDialog";
import { Field } from "../components/ui/controls";
import { Dialog, Empty, Menu, StatusBadge } from "../components/ui/display";
import { Icon } from "../components/ui/icons";
import { calc, downloadText } from "../lib/api";
import { KPI_META, Kpis, collectKpis } from "../lib/design";
import { fmt, relTime } from "../lib/format";
import { authorName, toast } from "../lib/stores";
import { DesignSummary, Project, Workspace, connectWorkspace } from "../lib/workspace";

const COLS: (keyof Kpis)[] = ["thrust_N", "isp_s", "pc_bar", "throat_d_mm", "q_max_MW_m2", "T_wall_max_K", "wall_margin_K"];

export default function ProjectPage() {
  const { pid } = useParams<{ pid: string }>();
  const [, nav] = useLocation();
  const [ws, setWs] = useState<Workspace | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [designs, setDesigns] = useState<DesignSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [live, setLive] = useState<Record<string, Kpis | "pending">>({});

  const load = async (w: Workspace) => {
    try {
      const r = await w.getProject(pid);
      setProject(r.project);
      setDesigns(r.designs);
    } catch (e) { setError((e as Error).message); }
  };
  useEffect(() => { connectWorkspace().then(({ ws }) => { setWs(ws); void load(ws); }); }, [pid]); // eslint-disable-line react-hooks/exhaustive-deps

  const baseline = designs?.find((d) => d.is_baseline);

  // Designs without a saved version (or imported without results): compute key
  // results from the working copy in the background, two at a time.
  useEffect(() => {
    if (!ws || !designs) return;
    const todo = designs.filter((d) => !Object.keys(d.kpis ?? {}).length && !live[d.id]);
    if (!todo.length) return;
    let cancelled = false;
    setLive((l) => ({ ...l, ...Object.fromEntries(todo.map((d) => [d.id, "pending" as const])) }));
    const queue = [...todo];
    const worker = async () => {
      for (let d = queue.shift(); d && !cancelled; d = queue.shift()) {
        try {
          const full = await ws.getDesign(pid, d.id);
          const perf = await calc.performance(full.config);
          const heat = await calc.heatFlux(full.config, 800).catch(() => null);
          const cool = full.config.regen ? await calc.cooling(full.config, "preview").catch(() => null) : null;
          if (!cancelled) setLive((l) => ({ ...l, [d!.id]: collectKpis(perf, heat, cool) }));
        } catch {
          if (!cancelled) setLive((l) => ({ ...l, [d!.id]: {} }));
        }
      }
    };
    void Promise.all([worker(), worker()]);
    return () => { cancelled = true; };
  }, [ws, designs]); // eslint-disable-line react-hooks/exhaustive-deps
  const kpisOf = (d: DesignSummary): { k: Record<string, unknown>; live: boolean; pending: boolean } => {
    if (Object.keys(d.kpis ?? {}).length) return { k: d.kpis, live: false, pending: false };
    const l = live[d.id];
    return l === "pending" || !l ? { k: {}, live: true, pending: l === "pending" } : { k: l as Record<string, unknown>, live: true, pending: false };
  };

  const exportProject = async () => {
    if (!ws || !project) return;
    const b = await ws.exportProject(pid);
    downloadText(JSON.stringify(b, null, 2), `${project.id}.resa-project.json`, "application/json");
  };
  const deleteProject = async () => {
    if (!ws || !project) return;
    if (!confirm(`Delete the project “${project.name}” and all its designs?${ws.kind === "server" ? " (It is moved to the workspace trash.)" : ""}`)) return;
    await ws.deleteProject(pid);
    toast("Project deleted");
    nav("/");
  };
  const setBaseline = async (d: DesignSummary) => {
    if (!ws) return;
    await ws.updateDesign(pid, d.id, { is_baseline: !d.is_baseline, author: authorName() });
    await load(ws);
  };
  const removeDesign = async (d: DesignSummary) => {
    if (!ws || !confirm(`Delete the design “${d.name}”?`)) return;
    await ws.deleteDesign(pid, d.id);
    await load(ws);
  };
  const duplicate = async (d: DesignSummary) => {
    if (!ws) return;
    const n = await ws.createDesign(pid, { name: `${d.name} copy`, author: authorName(), derived_from: { design_id: d.id } });
    nav(`/p/${pid}/d/${n.id}`);
  };

  if (error) return <><TopBar crumbs={[{ label: "Not found" }]} /><div className="page"><Empty title="Project not found">{error}</Empty></div></>;

  return (
    <>
      <TopBar crumbs={[{ label: project?.name ?? "…" }]} />
      <main className="page">
        <div className="page-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="eyebrow">Project</div>
            <h1>{project?.name ?? " "}</h1>
            <p>{project?.description || <span className="muted">No description yet.</span>}</p>
          </div>
          <div className="row" style={{ paddingTop: 20 }}>
            <Menu trigger={(open) => <button className="btn btn-icon" aria-label="Project actions" onClick={open}><Icon name="more" /></button>}
              items={[
                { label: "Edit name & description", icon: "edit", onClick: () => setEditing(true) },
                { label: "Export project file", icon: "download", onClick: exportProject },
                { divider: true, label: "", onClick: () => {} },
                { label: "Delete project", icon: "trash", danger: true, onClick: deleteProject },
              ]} />
            <button className="btn btn-primary" onClick={() => setCreating(true)}><Icon name="plus" size="sm" />New engine design</button>
          </div>
        </div>

        {designs === null ? <div className="skeleton" style={{ height: 180 }} /> : designs.length === 0 ? (
          <Empty title="No engine designs yet" action={<button className="btn btn-primary" onClick={() => setCreating(true)}><Icon name="plus" size="sm" />New engine design</button>}>
            An engine design is one complete configuration — propellants, operating point, chamber, cooling. Create one from a
            quick setup, copy an existing one, or import a YAML file.
          </Empty>
        ) : (
          <div className="card" style={{ overflowX: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 28 }} />
                  <th>Engine design</th>
                  <th>Status</th>
                  <th>Version</th>
                  {COLS.map((k) => <th key={k} className="num">{KPI_META[k].label}<span className="unit">{KPI_META[k].unit || "–"}</span></th>)}
                  <th>Last change</th>
                  <th style={{ width: 40 }} />
                </tr>
              </thead>
              <tbody>
                {designs.map((d) => (
                  <tr key={d.id} className="link" onClick={() => nav(`/p/${pid}/d/${d.id}`)}>
                    <td onClick={(e) => { e.stopPropagation(); void setBaseline(d); }} title={d.is_baseline ? "Baseline — others are compared to it" : "Make this the baseline"}>
                      <span style={{ color: d.is_baseline ? "var(--hot)" : "var(--ink-4)", cursor: "pointer" }}>
                        <svg className="icon" viewBox="0 0 24 24" style={{ fill: d.is_baseline ? "currentColor" : "none" }}><path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z" /></svg>
                      </span>
                    </td>
                    <td>
                      <div className="design-name">{d.name}{d.is_baseline && <span className="badge hot">baseline</span>}</div>
                      {d.derived_from && <div className="muted" style={{ fontSize: 12 }}>from {d.derived_from.design_name}{d.derived_from.version ? ` v${d.derived_from.version}` : ""}</div>}
                    </td>
                    <td><StatusBadge status={d.status} /></td>
                    <td className="mono" style={{ whiteSpace: "nowrap" }}>
                      {d.head_version ? `v${d.head_version}` : <span className="muted">—</span>}
                      {d.has_unsaved_changes && <span className="badge warn" style={{ marginLeft: 6 }} title="The working copy has changes not saved as a version">edited</span>}
                    </td>
                    {COLS.map((k) => {
                      const { k: kp, live: isLive, pending } = kpisOf(d);
                      const v = kp[k];
                      const b = baseline && baseline.id !== d.id ? kpisOf(baseline).k[k] : undefined;
                      return (
                        <td key={k} className="num" title={isLive ? "Computed from the working copy — save a version to record it" : undefined}>
                          {typeof v === "number" ? <span className={isLive ? "live" : ""}>{fmt(v, KPI_META[k].digits)}</span>
                            : pending ? <span className="skeleton" style={{ display: "inline-block", width: 36, height: 12 }} /> : <span className="muted">—</span>}
                          {typeof v === "number" && typeof b === "number" && <Delta k={k} v={v} b={b} />}
                        </td>
                      );
                    })}
                    <td style={{ whiteSpace: "nowrap", fontSize: 12.5 }}><div className="muted">{relTime(d.updated_at)}</div>{d.updated_by && d.updated_by !== "anonymous" && <div>{d.updated_by}</div>}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <Menu trigger={(open) => <button className="btn btn-ghost btn-sm btn-icon" aria-label="Design actions" onClick={open}><Icon name="more" size="sm" /></button>}
                        items={[
                          { label: "Duplicate", icon: "copy", onClick: () => duplicate(d) },
                          { label: d.is_baseline ? "Clear baseline" : "Set as baseline", icon: "star", onClick: () => setBaseline(d) },
                          { label: "Delete", icon: "trash", danger: true, onClick: () => removeDesign(d) },
                        ]} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {designs && designs.length > 0 && (
          <p className="muted" style={{ fontSize: 12.5, marginTop: 12 }}>
            Key results are those of each design’s latest saved version; <i>italic</i> values are computed live from working copies without saved results. {baseline ? <>Coloured deltas compare against the baseline <b>{baseline.name}</b>.</> : "Star a design to make it the baseline for comparisons."}
          </p>
        )}
      </main>
      {creating && ws && <NewDesignDialog ws={ws} pid={pid} designs={designs ?? []} onClose={() => setCreating(false)} onCreated={(d) => nav(`/p/${pid}/d/${d.id}`)} />}
      {editing && ws && project && <EditProjectDialog ws={ws} project={project} onClose={() => setEditing(false)} onSaved={(p) => { setProject(p); setEditing(false); }} />}
    </>
  );
}

function Delta({ k, v, b }: { k: keyof Kpis; v: number; b: number }) {
  const meta = KPI_META[k];
  const d = v - b;
  if (Math.abs(d) < Math.pow(10, -meta.digits) / 2) return null;
  const good = meta.better ? (meta.better === "up" ? d > 0 : d < 0) : null;
  return <span className={`delta ${good === null ? "flat" : good ? "up" : "down"}`} style={{ marginLeft: 6 }}>{d > 0 ? "+" : ""}{fmt(d, meta.digits)}</span>;
}

function EditProjectDialog({ ws, project, onClose, onSaved }: { ws: Workspace; project: Project; onClose(): void; onSaved(p: Project): void }) {
  const [name, setName] = useState(project.name);
  const [desc, setDesc] = useState(project.description);
  return (
    <Dialog title="Project details" onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!name.trim()}
        onClick={async () => onSaved(await ws.updateProject(project.id, { name: name.trim(), description: desc.trim() }))}>Save</button></>}>
      <Field label="Project name"><input className="plain-input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Description"><textarea className="textarea" value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
    </Dialog>
  );
}

