import { useEffect, useRef, useState } from "react";
import { useLocation, useParams } from "wouter";
import { DEFAULT_QUICK, QuickSetup, specFrom } from "../components/NewDesignDialog";
import { Field, Select } from "../components/ui/controls";
import { Callout, Dialog } from "../components/ui/display";
import { Icon } from "../components/ui/icons";
import { newDesign } from "../lib/design";
import { Section, readScratch, useSession, writeScratch } from "../lib/session";
import { authorName, toast, useCatalog } from "../lib/stores";
import { Project, Workspace, connectWorkspace } from "../lib/workspace";
import { DesignWorkspace, SECTIONS } from "./DesignWorkspace";

export function EstimatePage() {
  const { section } = useParams<{ section?: string }>();
  const catalog = useCatalog((s) => s.catalog);
  const [ready, setReady] = useState(() => !!readScratch());
  const [restart, setRestart] = useState(false);
  const [saveTo, setSaveTo] = useState(false);
  const [epoch, setEpoch] = useState(0);

  useEffect(() => {
    if (ready || !catalog) return;
    const spec = specFrom(DEFAULT_QUICK, "QUICK-1", catalog.propellants);
    if (spec) { writeScratch(newDesign(spec)); setReady(true); }
  }, [catalog, ready]);

  const sec = (SECTIONS.find((s) => s.id === section)?.id ?? "performance") as Section;
  if (!ready) return <div className="page"><div className="skeleton" style={{ height: 300 }} /></div>;
  return (
    <>
      <DesignWorkspace
        key={epoch}
        source={{ kind: "scratch" }}
        section={sec}
        base="/estimate"
        crumbs={[{ label: "Quick estimate" }]}
        scratchActions={<>
          <button className="btn" onClick={() => setRestart(true)}><Icon name="restore" size="sm" />Start over</button>
          <button className="btn btn-primary" onClick={() => setSaveTo(true)}><Icon name="folder" size="sm" />Save to a project</button>
        </>}
      />
      {restart && <RestartDialog onClose={() => setRestart(false)} onDone={() => { setRestart(false); setEpoch((e) => e + 1); }} />}
      {saveTo && <SaveToProjectDialog onClose={() => setSaveTo(false)} />}
    </>
  );
}

function RestartDialog({ onClose, onDone }: { onClose(): void; onDone(): void }) {
  const catalog = useCatalog((s) => s.catalog);
  const [q, setQ] = useState<typeof DEFAULT_QUICK | { ox: string; fuel: string; thrust_N: number; pc_bar: number; of_ratio: number | null; ambient: "sea_level" | "vacuum" }>(DEFAULT_QUICK);
  return (
    <Dialog title="New quick estimate" sub="Four inputs are enough; everything else starts from sensible defaults you can refine." onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={() => {
        const spec = catalog && specFrom(q, "QUICK-1", catalog.propellants);
        if (spec) { writeScratch(newDesign(spec)); onDone(); }
      }}>Estimate</button></>}>
      <QuickSetup spec={q} onChange={setQ} />
    </Dialog>
  );
}

function SaveToProjectDialog({ onClose }: { onClose(): void }) {
  const [, nav] = useLocation();
  const config = useSession((s) => s.config);
  const [ws, setWs] = useState<Workspace | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [pid, setPid] = useState<string>("__new");
  const [projectName, setProjectName] = useState("");
  const [name, setName] = useState("Baseline");
  const [busy, setBusy] = useState(false);
  const touched = useRef(false);
  useEffect(() => {
    connectWorkspace().then(async ({ ws }) => {
      setWs(ws);
      const list = await ws.listProjects();
      setProjects(list);
      // default to the most recent project unless the user already picked
      if (list[0] && !touched.current) setPid(list[0].id);
    }).catch((e) => toast((e as Error).message, "bad"));
  }, []);
  const save = async () => {
    if (!ws || !config) return;
    setBusy(true);
    try {
      let target = pid;
      if (pid === "__new") target = (await ws.createProject(projectName.trim() || "New engine", "", authorName())).id;
      const d = await ws.createDesign(target, { name: name.trim() || "Baseline", config, author: authorName() });
      await ws.createVersion(target, d.id, "Created from a quick estimate", authorName(), useSession.getState().kpis() as Record<string, unknown>);
      toast("Saved as an engine design — version 1");
      nav(`/p/${target}/d/${d.id}`);
    } catch (e) { toast((e as Error).message, "bad"); setBusy(false); }
  };
  return (
    <Dialog title="Save to a project" sub="Your estimate becomes an engine design with version history." onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy} onClick={save}>Save design</button></>}>
      <Field label="Project">
        <Select value={pid} onChange={(v) => { touched.current = true; setPid(v); }} options={[...projects.map((p) => ({ value: p.id, label: p.name })), { value: "__new", label: "＋ New project…" }]} />
      </Field>
      {pid === "__new" && <Field label="New project name"><input className="plain-input" value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="e.g. Upper stage 2 kN" /></Field>}
      <Field label="Design name"><input className="plain-input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Callout tone="info">The quick estimate stays available on this device; the project copy is the one your team sees.</Callout>
    </Dialog>
  );
}
