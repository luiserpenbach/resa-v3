import { useEffect, useRef, useState } from "react";
import { useLocation } from "wouter";
import { Change, KPI_META, Kpis, diffDesigns } from "../lib/design";
import { fmt, relTime } from "../lib/format";
import { useSession } from "../lib/session";
import { authorName, toast, useSettings } from "../lib/stores";
import { Version, VersionSummary, connectWorkspace } from "../lib/workspace";
import { Field } from "./ui/controls";
import { Callout, Dialog, Drawer, Spinner } from "./ui/display";
import { Icon } from "./ui/icons";

const SHOWN: (keyof Kpis)[] = ["isp_s", "thrust_N", "pc_bar", "throat_d_mm", "q_max_MW_m2", "T_wall_max_K", "wall_margin_K", "dp_bar"];

function KpiLine({ k, prev }: { k: Record<string, unknown>; prev?: Record<string, unknown> }) {
  const items = SHOWN.filter((key) => typeof k[key] === "number");
  if (!items.length) return null;
  return (
    <div className="vkpis">
      {items.map((key) => {
        const meta = KPI_META[key];
        const v = k[key] as number, p = prev?.[key] as number | undefined;
        const d = typeof p === "number" ? v - p : 0;
        const show = typeof p === "number" && Math.abs(d) >= Math.pow(10, -meta.digits) / 2;
        const good = meta.better ? (meta.better === "up" ? d > 0 : d < 0) : null;
        return (
          <span key={key}>{meta.label} {fmt(v, meta.digits)}{meta.unit && ` ${meta.unit}`}
            {show && <span className={`delta ${good === null ? "flat" : good ? "up" : "down"}`} style={{ marginLeft: 4 }}>{d > 0 ? "+" : ""}{fmt(d, meta.digits)}</span>}
          </span>
        );
      })}
    </div>
  );
}

function Changes({ changes }: { changes: Change[] }) {
  if (!changes.length) return <p className="muted" style={{ margin: 0 }}>No input changes.</p>;
  return (
    <div>
      <div className="diff-row" style={{ fontWeight: 600, color: "var(--ink-3)", fontSize: 11 }}><span>INPUT</span><span>BEFORE</span><span>NOW</span></div>
      {changes.slice(0, 60).map((c) => (
        <div className="diff-row" key={c.path} title={c.path}><span>{c.label}</span><span className="old">{c.before}</span><span className="new">{c.after}</span></div>
      ))}
      {changes.length > 60 && <p className="muted">…and {changes.length - 60} more</p>}
    </div>
  );
}

export function HistoryDrawer({ onClose }: { onClose(): void }) {
  const { versions, meta, config, source, restore, refreshVersions, kpis } = useSession();
  const [, nav] = useLocation();
  const [open, setOpen] = useState<Version | null>(null);
  const [loading, setLoading] = useState<number | null>(null);
  useEffect(() => { void refreshVersions(); }, [refreshVersions]);
  if (source?.kind !== "project") return null;
  const { pid, did } = source;
  const current = kpis();

  const view = async (n: number) => {
    setLoading(n);
    try {
      const { ws } = await connectWorkspace();
      setOpen(await ws.getVersion(pid, did, n));
    } catch (e) {
      toast((e as Error).message, "bad");
    } finally {
      setLoading(null);
    }
  };
  const doRestore = async (v: VersionSummary) => {
    if (!confirm(`Replace the working copy with version ${v.number}? Your current edits stay recoverable with Undo.`)) return;
    try {
      await restore(v.number);
      toast(`Restored version ${v.number}`);
      onClose();
    } catch (e) { toast((e as Error).message, "bad"); }
  };
  const branch = async (v: VersionSummary) => {
    const name = prompt("Name of the new design", `${meta?.name ?? "Design"} (from v${v.number})`);
    if (!name) return;
    try {
      const { ws } = await connectWorkspace();
      const d = await ws.createDesign(pid, { name, author: authorName(), derived_from: { design_id: did, version: v.number } });
      toast(`Created “${d.name}”`);
      onClose();
      nav(`/p/${pid}/d/${d.id}`);
    } catch (e) { toast((e as Error).message, "bad"); }
  };

  return (
    <Drawer title="History" onClose={onClose}>
      {open ? (
        <div style={{ padding: 18, display: "grid", gap: 14 }}>
          <button className="btn btn-ghost btn-sm" style={{ justifySelf: "start" }} onClick={() => setOpen(null)}><Icon name="back" size="sm" />All versions</button>
          <div>
            <div className="eyebrow">Version {open.number} → working copy</div>
            <h3 style={{ fontSize: 16, marginTop: 4 }}>{open.message}</h3>
            <div className="muted" style={{ fontSize: 12 }}>{open.author} · {new Date(open.created_at).toLocaleString()}</div>
          </div>
          <section className="card card-pad">
            <div className="eyebrow" style={{ marginBottom: 6 }}>Key results then → now</div>
            <KpiLine k={current as Record<string, unknown>} prev={open.kpis} />
          </section>
          <section className="card card-pad"><Changes changes={diffDesigns(open.config, config ?? {})} /></section>
          <div className="row">
            <button className="btn" onClick={() => doRestore(open)}><Icon name="restore" size="sm" />Restore this version</button>
            <button className="btn" onClick={() => branch(open)}><Icon name="copy" size="sm" />New design from it</button>
          </div>
        </div>
      ) : (
        <div>
          <div className="version working">
            <div className="vno">now</div>
            <div>
              <div className="vmsg">Working copy</div>
              <div className="vmeta">{meta?.has_unsaved_changes ? "has changes not yet saved as a version" : "identical to the latest version"} · saved automatically</div>
              <KpiLine k={current as Record<string, unknown>} prev={versions[0]?.kpis} />
            </div>
          </div>
          {versions.length === 0 && <p className="muted" style={{ padding: "18px 18px 0 76px" }}>No versions yet — save one to mark a milestone.</p>}
          {versions.map((v, i) => (
            <div className="version" key={v.number}>
              <div className="vno">v{v.number}</div>
              <div>
                <div className="vmsg">{v.message}</div>
                <div className="vmeta">{v.author} · {relTime(v.created_at)}</div>
                <KpiLine k={v.kpis} prev={versions[i + 1]?.kpis} />
                <div className="vactions">
                  <button className="btn btn-sm" onClick={() => view(v.number)} disabled={loading !== null}>
                    {loading === v.number ? <Spinner /> : <Icon name="compare" size="sm" />}Compare</button>
                  <button className="btn btn-sm btn-ghost" onClick={() => doRestore(v)}><Icon name="restore" size="sm" />Restore</button>
                  <button className="btn btn-sm btn-ghost" onClick={() => branch(v)}><Icon name="copy" size="sm" />Branch</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Drawer>
  );
}

export function SaveVersionDialog({ onClose }: { onClose(): void }) {
  const { meta, config, source, saveVersion, kpis, errors } = useSession();
  const { author, setAuthor } = useSettings();
  const [name, setName] = useState(author);
  const [message, setMessage] = useState("");
  const [prev, setPrev] = useState<Version | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (source?.kind !== "project" || !meta?.head_version) return;
    connectWorkspace().then(({ ws }) => ws.getVersion(source.pid, source.did, meta.head_version!)).then(setPrev).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const changes = prev && config ? diffDesigns(prev.config, config) : null;
  const inflight = useRef(false);
  const submit = async () => {
    if (!message.trim() || busy || inflight.current) return;
    inflight.current = true;
    if (name.trim() !== author) setAuthor(name.trim());
    setBusy(true);
    try {
      await saveVersion(message.trim());
      toast("Version saved");
      onClose();
    } catch (e) { toast((e as Error).message, "bad"); setBusy(false); inflight.current = false; }
  };
  return (
    <Dialog wide title={`Save version ${(meta?.head_version ?? 0) + 1}`} sub="A version is a named, permanent snapshot of this design and its key results." onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy || !message.trim()} onClick={submit}>Save version</button></>}>
      <div className="grid-2">
        <Field label="What changed and why?">
          <input className="plain-input" autoFocus value={message} onChange={(e) => setMessage(e.target.value)}
            placeholder="e.g. Raised Pc to 25 bar for smaller throat" onKeyDown={(e) => { if (e.key === "Enter") void submit(); }} />
        </Field>
        <Field label="Your name"><input className="plain-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="shown in the history" /></Field>
      </div>
      {errors.length > 0 && <Callout tone="warn">Some inputs are invalid — the saved key results are from the last valid state.</Callout>}
      <section>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Key results captured</div>
        <KpiLine k={kpis() as Record<string, unknown>} prev={prev?.kpis} />
      </section>
      {meta?.head_version ? (
        <section>
          <div className="eyebrow" style={{ marginBottom: 6 }}>Changes since version {meta.head_version}</div>
          {changes ? <Changes changes={changes} /> : <Spinner />}
        </section>
      ) : <Callout tone="info">This will be the first version of the design.</Callout>}
    </Dialog>
  );
}
