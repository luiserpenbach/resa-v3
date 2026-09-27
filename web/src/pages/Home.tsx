import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "wouter";
import { TopBar } from "../App";
import { EngineDrawing } from "../components/charts/Drawing";
import { Field } from "../components/ui/controls";
import { Dialog, Empty } from "../components/ui/display";
import { Icon } from "../components/ui/icons";
import { relTime } from "../lib/format";
import { authorName, readRecents, toast } from "../lib/stores";
import { Bundle, Project, Workspace, WorkspaceInfo, connectWorkspace } from "../lib/workspace";

/** Illustrative bell contour (normalized) for the hero drawing. */
export function sampleContour() {
  const x: number[] = [], r: number[] = [];
  const Rc = 1.0, Rt = 0.42, Re = 1.25;
  for (let i = 0; i <= 20; i++) { x.push(-2.6 + (i / 20) * 1.2); r.push(Rc); }
  for (let i = 1; i <= 40; i++) {
    const t = i / 40;
    x.push(-1.4 + t * 1.4);
    r.push(Rt + (Rc - Rt) * (0.5 + 0.5 * Math.cos(Math.PI * t)));
  }
  for (let i = 1; i <= 60; i++) {
    const t = i / 60;
    x.push(t * 3.1);
    r.push(Rt + (Re - Rt) * (1 - Math.pow(1 - t, 1.9)));
  }
  return { x, r };
}
const HERO = sampleContour();
const HERO_HEAT = { x: HERO.x, q: HERO.r.map((r) => Math.pow(HERO.r[0] / r, 1.8)) };

export default function Home() {
  const [, nav] = useLocation();
  const [ws, setWs] = useState<Workspace | null>(null);
  const [info, setInfo] = useState<WorkspaceInfo | null>(null);
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const recents = readRecents();

  const refresh = async (w = ws) => { if (w) setProjects(await w.listProjects()); };
  useEffect(() => {
    connectWorkspace().then(({ ws, info }) => { setWs(ws); setInfo(info); void refresh(ws); })
      .catch((e) => toast(String(e.message ?? e), "bad"));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadExamples = async () => {
    if (!ws) return;
    setBusy(true);
    try {
      const made = await ws.importExamples(authorName());
      toast(made.length ? `Added ${made.length} example projects` : "Examples are already in your workspace");
      await refresh();
    } catch (e) { toast((e as Error).message, "bad"); }
    setBusy(false);
  };

  const importFile = async (f: File) => {
    if (!ws) return;
    try {
      const bundle = JSON.parse(await f.text()) as Bundle;
      const p = await ws.importBundle(bundle, authorName());
      toast(`Imported “${p.name}”`);
      nav(`/p/${p.id}`);
    } catch (e) { toast(`Could not import: ${(e as Error).message}`, "bad"); }
  };

  return (
    <>
      <TopBar />
      <main className="home">
        <section className="hero">
          <div>
            <div className="eyebrow">Rocket engine sizing &amp; cooling design</div>
            <h1 className="display" style={{ marginTop: 10 }}>What do you need<br />to <em>know</em> today?</h1>
            <p className="lede">Start with the answer you need — an Isp and throat size, the heat load on the walls, or a full
              cooling-channel design. Everything is one engine design, so a quick estimate grows into a detailed one without re-typing.</p>
          </div>
          <div className="hero-art" aria-hidden="true">
            <EngineDrawing x={HERO.x} r={HERO.r} heat={HERO_HEAT} height={210} compact />
          </div>
        </section>

        <section className="tasks">
          <button className="task hot" onClick={() => nav("/estimate")}>
            <span className="task-no">01</span>
            <h3>Quick estimate</h3>
            <p>Thrust, chamber pressure, propellants — get Isp, flow rates, throat and exit size in seconds. No project needed.</p>
            <span className="task-go">Start estimating <Icon name="arrow" size="sm" /></span>
          </button>
          <button className="task hot" onClick={() => nav("/estimate/heat")}>
            <span className="task-no">02</span>
            <h3>Heat load</h3>
            <p>Heat flux along the chamber and nozzle, total heat into the wall, and whether your propellant can absorb it.</p>
            <span className="task-go">Check the heat load <Icon name="arrow" size="sm" /></span>
          </button>
          <button className="task cool" onClick={() => nav("/estimate/cooling")}>
            <span className="task-no">03</span>
            <h3>Cooling channels</h3>
            <p>Lay out regenerative channels, check wall temperature against the material limit and follow the coolant on a p–h diagram.</p>
            <span className="task-go">Design channels <Icon name="arrow" size="sm" /></span>
          </button>
        </section>

        {recents.length > 0 && (
          <section style={{ marginBottom: 40 }}>
            <div className="section-head"><h2>Continue where you left off</h2></div>
            <div className="row-wrap">
              {recents.map((r) => (
                <Link key={`${r.pid}/${r.did}`} href={`/p/${r.pid}/d/${r.did}`} className="chip" style={{ textDecoration: "none", padding: "7px 12px" }}>
                  <Icon name="flame" size="sm" /><b>{r.name}</b><span className="muted">{r.project} · {relTime(r.at)}</span>
                </Link>
              ))}
            </div>
          </section>
        )}

        <section>
          <div className="section-head">
            <h2>Projects</h2>
            <span className="muted" style={{ paddingBottom: 6 }}>a project holds the engine designs of one program, with their full history</span>
            <span className="spacer" />
            <input ref={fileRef} type="file" accept=".json,application/json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void importFile(f); e.target.value = ""; }} />
            <button className="btn" onClick={() => fileRef.current?.click()}><Icon name="upload" size="sm" />Import</button>
            <button className="btn btn-primary" onClick={() => setCreating(true)}><Icon name="plus" size="sm" />New project</button>
          </div>
          {projects === null ? (
            <div className="projects">{[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 120 }} />)}</div>
          ) : projects.length === 0 ? (
            <Empty title="No projects yet"
              action={<div className="row">
                <button className="btn btn-primary" onClick={() => setCreating(true)}><Icon name="plus" size="sm" />New project</button>
                {info?.examples_available && <button className="btn" disabled={busy} onClick={loadExamples}>Load example projects</button>}
              </div>}>
              Create a project for your engine program, or load the example engines (E2, EX15, Spark-50) to explore.
            </Empty>
          ) : (
            <div className="projects">
              {projects.map((p) => (
                <Link key={p.id} href={`/p/${p.id}`} className="project-card">
                  <div className="row"><Icon name="folder" /><h3>{p.name}</h3></div>
                  <p>{p.description || "No description"}</p>
                  <div className="meta">
                    <span>{p.design_count} design{p.design_count === 1 ? "" : "s"}</span>
                    <span>updated {relTime(p.updated_at)}</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
          {info && (
            <div className="storage-note">
              <Icon name={info.storage === "browser" ? "info" : "save"} size="sm" />
              {info.storage === "files" && <span>Projects are saved as plain YAML in the <b>{info.location}</b> — commit it to git to share with your team.</span>}
              {info.storage === "database" && <span>Projects are saved in the shared <b>{info.location}</b>; everyone using this deployment sees the same workspace.</span>}
              {info.storage === "browser" && <span>Projects are saved in <b>this browser</b>. Export a project to share it, or connect a database to the deployment for a shared team workspace.</span>}
              {projects && projects.length > 0 && info.examples_available && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={loadExamples}>Add example projects</button>}
            </div>
          )}
        </section>
      </main>
      {creating && ws && <NewProjectDialog ws={ws} onClose={() => setCreating(false)} onCreated={(p) => nav(`/p/${p.id}`)} />}
    </>
  );
}

export function NewProjectDialog({ ws, onClose, onCreated }: { ws: Workspace; onClose(): void; onCreated(p: Project): void }) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);
  const submit = async () => {
    if (!name.trim() || busy || inflight.current) return;
    inflight.current = true;
    setBusy(true);
    try { onCreated(await ws.createProject(name.trim(), desc.trim(), authorName())); }
    catch (e) { toast((e as Error).message, "bad"); setBusy(false); inflight.current = false; }
  };
  return (
    <Dialog title="New project" sub="One project per engine program. It holds the program’s engine designs and their history." onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!name.trim() || busy} onClick={submit}>Create project</button></>}>
      <Field label="Project name">
        <input className="plain-input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Upper stage 2 kN"
          onKeyDown={(e) => { if (e.key === "Enter") void submit(); }} />
      </Field>
      <Field label="What is it for?" hint="Optional — a line of context for your team.">
        <textarea className="textarea" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Program goal, requirements, test campaign…" />
      </Field>
    </Dialog>
  );
}
