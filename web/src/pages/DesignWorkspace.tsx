import { ReactNode, useEffect, useState } from "react";
import { Link, useLocation } from "wouter";
import { TopBar } from "../App";
import { HistoryDrawer, SaveVersionDialog } from "../components/History";
import { Menu, Spinner, StatusBadge } from "../components/ui/display";
import { Icon } from "../components/ui/icons";
import { downloadText, yaml } from "../lib/api";
import { fmt, relTime, sig } from "../lib/format";
import { Section, Source, useSession } from "../lib/session";
import { pushRecent, toast } from "../lib/stores";
import { BaseContext } from "../lib/nav";
import { ChamberSection } from "./sections/Chamber";
import { CoolingSection } from "./sections/Cooling";
import { HeatSection } from "./sections/Heat";
import { PerformanceSection } from "./sections/Performance";
import { RangeSection } from "./sections/Range";
import { SummarySection } from "./sections/Summary";
import { TradeSection } from "./sections/Trade";

export const SECTIONS: { id: Section; title: string; icon: string }[] = [
  { id: "performance", title: "Performance", icon: "gauge" },
  { id: "chamber", title: "Chamber & nozzle", icon: "nozzle" },
  { id: "heat", title: "Heat load", icon: "flame" },
  { id: "cooling", title: "Cooling channels", icon: "channels" },
  { id: "range", title: "Operating range", icon: "range" },
  { id: "trade", title: "Trade study", icon: "trade" },
  { id: "summary", title: "Design sheet", icon: "report" },
];

function useNavSummaries(): Record<Section, { text: string; tone?: "ok" | "bad" }> {
  const { perf, heat, cool, config, errors } = useSession();
  const p = perf.data?.performance, g = perf.data?.geometry;
  const cs = cool.data?.ok ? cool.data.summary : null;
  const pending = errors.length ? { text: `${errors.length} input issue${errors.length > 1 ? "s" : ""}`, tone: "bad" as const } : null;
  return {
    performance: pending ?? { text: p ? `${fmt(p.isp_s, 1)} s · ${sig(p.thrust_N, 3)} N` : "—" },
    chamber: { text: g ? `throat Ø ${sig(g.throat_diameter_m * 1e3, 3)} mm` : "—" },
    heat: { text: heat.data ? `peak ${sig(heat.data.summary.q_max_W_m2 / 1e6, 3)} MW/m²` : "—" },
    cooling: !config?.regen ? { text: "not designed yet" } : cs
      ? { text: `wall ${fmt(cs.T_wall_max_K, 0)} K · ${cs.wall_margin_K >= 0 ? "+" : ""}${fmt(cs.wall_margin_K, 0)} K`, tone: cs.wall_margin_K < 0 ? "bad" : "ok" }
      : { text: cool.error ? "solve failed" : "open to solve", tone: cool.error ? "bad" : undefined },
    range: { text: config?.offdesign ? "sweeps set up" : "throttle & mixture" },
    trade: { text: "vary one input" },
    summary: { text: "print or export" },
  };
}

export function DesignWorkspace({ source, section, base, crumbs, scratchActions }: {
  source: Source; section: Section; base: string; crumbs: { label: string; href?: string }[]; scratchActions?: ReactNode;
}) {
  const s = useSession();
  const [, nav] = useLocation();
  const [history, setHistory] = useState(false);
  const [saving, setSaving] = useState(false);
  const summaries = useNavSummaries();
  const key = source.kind === "project" ? `${source.pid}/${source.did}` : "scratch";

  useEffect(() => {
    void useSession.getState().open(source);
    return () => useSession.getState().close();
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { s.setSection(section); }, [section]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (source.kind === "project" && s.meta) pushRecent({ pid: source.pid, did: source.did, name: s.meta.name, project: s.projectName });
  }, [s.meta?.name, s.projectName]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      const k = e.key.toLowerCase();
      const t = e.target as HTMLElement | null;
      const inText = !!t && (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.isContentEditable || !!t.closest?.(".dialog"));
      if (k === "z" && !inText) { e.preventDefault(); if (e.shiftKey) s.redo(); else s.undo(); }
      else if (k === "y" && !inText) { e.preventDefault(); s.redo(); }
      else if (k === "s") { e.preventDefault(); if (source.kind === "project") setSaving(true); }
    };
    const onUnload = (e: BeforeUnloadEvent) => {
      if (useSession.getState().saveState === "dirty" || useSession.getState().saveState === "saving") {
        void useSession.getState().flush();
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onUnload);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("beforeunload", onUnload); };
  }, [source.kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const exportYaml = async () => {
    if (!s.config) return;
    const { text } = await yaml.dump(s.config);
    downloadText(text, `${s.config.engine ?? "engine"}.yaml`, "text/yaml");
  };

  if (s.loadError) {
    return (<><TopBar crumbs={crumbs} /><div className="page"><div className="empty"><h3>Could not open this design</h3><p>{s.loadError}</p><Link href="/" className="btn">Back to workspace</Link></div></div></>);
  }

  const busy = s.perf.loading || s.heat.loading || s.cool.loading;
  const Body = { performance: PerformanceSection, chamber: ChamberSection, heat: HeatSection, cooling: CoolingSection,
    range: RangeSection, trade: TradeSection, summary: SummarySection }[section];

  return (
    <>
      <TopBar crumbs={crumbs}>
        <div className="row" style={{ gap: 2 }}>
          <button className="btn btn-ghost btn-icon" title="Undo (Ctrl+Z)" disabled={!s.canUndo} onClick={s.undo}><Icon name="undo" /></button>
          <button className="btn btn-ghost btn-icon" title="Redo (Ctrl+Shift+Z)" disabled={!s.canRedo} onClick={s.redo}><Icon name="redo" /></button>
        </div>
        {source.kind === "project" ? (
          <>
            <SaveState />
            <button className="btn" onClick={() => setHistory(true)}><Icon name="history" size="sm" />History</button>
            <button className="btn btn-primary" onClick={() => setSaving(true)} title="Save a named version (Ctrl+S)"><Icon name="check" size="sm" />Save version</button>
          </>
        ) : scratchActions}
        <Menu trigger={(open) => <button className="btn btn-ghost btn-icon" aria-label="More" onClick={open}><Icon name="more" /></button>}
          items={[
            { label: "Download engine YAML", icon: "download", onClick: exportYaml },
            { label: "Print design sheet", icon: "report", onClick: () => nav(`${base}/summary`) },
            ...(source.kind === "project" ? [
              { divider: true, label: "", onClick: () => {} },
              ...(["concept", "preliminary", "detailed", "frozen"] as const).map((st) => ({
                label: <>Mark as <StatusBadge status={st} /></>, onClick: () => s.patchMeta({ status: st }).then(() => toast(`Status set to ${st}`), (e) => toast((e as Error).message, "bad")),
              })),
            ] : []),
          ]} />
      </TopBar>
      <div className="ws">
        <nav className="ws-nav" aria-label="Design sections">
          <TitleBlock source={source} />
          {SECTIONS.map((sec, i) => (
            <span key={sec.id} style={{ display: "contents" }}>
              {i === 4 && <div className="nav-sep" />}
              <Link href={`${base}/${sec.id}`} className={`nav-item${sec.id === section ? " on" : ""}`}>
                <Icon name={sec.icon} />
                <span className="nav-t">{sec.title}</span>
                <span className={`nav-s${summaries[sec.id].tone ? ` ${summaries[sec.id].tone}` : ""}`}>{summaries[sec.id].text}</span>
              </Link>
            </span>
          ))}
          <div className="nav-foot">
            <div className="row" style={{ gap: 6 }}>{busy ? <><Spinner /> computing…</> : s.perf.data ? <>computed in {fmt(s.perf.data.elapsed_s, 2)} s</> : null}</div>
            <div>Chemistry: {s.perf.data?.propellant_states.chemistry === "table" ? "table" : "NASA CEA equilibrium"}</div>
          </div>
        </nav>
        <BaseContext.Provider value={base}>
          {s.config ? <Body /> : <div className="ws-results"><div className="skeleton" style={{ height: 300 }} /></div>}
        </BaseContext.Provider>
      </div>
      {history && <HistoryDrawer onClose={() => setHistory(false)} />}
      {saving && <SaveVersionDialog onClose={() => setSaving(false)} />}
    </>
  );
}

function TitleBlock({ source }: { source: Source }) {
  const { meta, projectName, config } = useSession();
  const name = source.kind === "scratch" ? "Quick estimate" : meta?.name ?? "…";
  return (
    <div className="titleblock" aria-label="Design identification">
      <div><span className="tb-v tb-name">{name}</span></div>
      <div><span className="tb-k">Project</span><span className="tb-v">{source.kind === "scratch" ? "— scratchpad" : projectName}</span></div>
      <div><span className="tb-k">Engine</span><span className="tb-v">{config?.engine ?? "—"}</span></div>
      <div><span className="tb-k">Version</span><span className="tb-v">{meta?.head_version ? `v${meta.head_version}${meta.has_unsaved_changes ? " + edits" : ""}` : source.kind === "scratch" ? "not versioned" : "draft"}</span></div>
      {meta && <div><span className="tb-k">Status</span><span className="tb-v" style={{ fontFamily: "var(--font-ui)", textTransform: "capitalize" }}>{meta.status}</span></div>}
      {meta && <div><span className="tb-k">Changed</span><span className="tb-v">{relTime(meta.updated_at)}</span></div>}
    </div>
  );
}

function SaveState() {
  const { saveState, meta, flush } = useSession();
  const label = { saved: meta?.has_unsaved_changes ? "Draft saved" : "All saved", dirty: "Editing…", saving: "Saving…", error: "Not saved — retry", conflict: "Changed elsewhere" }[saveState];
  return (
    <button className={`btn btn-ghost save-state ${saveState}`} onClick={() => saveState === "conflict" ? window.location.reload() : void flush()}
      title={saveState === "conflict" ? "Reload to get the latest version" : "Your working copy saves automatically; save a version to mark a milestone."}>
      <span className="dot" />{label}
    </button>
  );
}
