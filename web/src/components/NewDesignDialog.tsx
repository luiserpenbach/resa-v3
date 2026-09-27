import { useEffect, useRef, useState } from "react";
import { Design, yaml } from "../lib/api";
import { DEFAULT_OF, PropChoice, QuickSpec, newDesign } from "../lib/design";
import { readScratch } from "../lib/session";
import { authorName, toast, useCatalog } from "../lib/stores";
import { DesignFull, DesignSummary, Workspace } from "../lib/workspace";
import { Field, NumberInput, Segmented, Select } from "./ui/controls";
import { Callout, Dialog } from "./ui/display";

type Start = "quick" | "copy" | "estimate" | "file";

export function QuickSetup({ spec, onChange }: { spec: Omit<QuickSpec, "name" | "ox" | "fuel"> & { ox: string; fuel: string }; onChange(s: typeof spec): void }) {
  const catalog = useCatalog((s) => s.catalog);
  const props = catalog?.propellants ?? [];
  const set = (patch: Partial<typeof spec>) => {
    const next = { ...spec, ...patch };
    if ((patch.ox || patch.fuel) && !("of_ratio" in patch)) next.of_ratio = DEFAULT_OF[`${next.ox}/${next.fuel}`] ?? null;
    onChange(next);
  };
  return (
    <div className="stack">
      <div className="grid-2">
        <Field label="Oxidizer">
          <Select value={spec.ox} onChange={(v) => set({ ox: v })}
            options={props.filter((p) => p.role === "oxidizer").map((p) => ({ value: p.id, label: p.label }))} />
        </Field>
        <Field label="Fuel">
          <Select value={spec.fuel} onChange={(v) => set({ fuel: v })}
            options={props.filter((p) => p.role === "fuel").map((p) => ({ value: p.id, label: p.label }))} />
        </Field>
      </div>
      <div className="grid-3">
        <Field label="Thrust"><NumberInput value={spec.thrust_N} unit="N" onChange={(v) => v && set({ thrust_N: v })} /></Field>
        <Field label="Chamber pressure"><NumberInput value={spec.pc_bar} unit="bar" onChange={(v) => v && set({ pc_bar: v })} /></Field>
        <Field label="Mixture ratio" hint="blank = best Isp"><NumberInput value={spec.of_ratio} placeholder="best" unit="O/F" onChange={(v) => set({ of_ratio: v })} /></Field>
      </div>
      <Field label="Operates at">
        <Segmented full value={spec.ambient} onChange={(v) => set({ ambient: v })}
          options={[{ value: "sea_level", label: "Sea level" }, { value: "vacuum", label: "Vacuum (upper stage / space)" }]} />
      </Field>
    </div>
  );
}

export const DEFAULT_QUICK = { ox: "lox", fuel: "ethanol", thrust_N: 2000, pc_bar: 20, of_ratio: 1.6 as number | null, ambient: "sea_level" as const };

export function specFrom(q: typeof DEFAULT_QUICK | { ox: string; fuel: string; thrust_N: number; pc_bar: number; of_ratio: number | null; ambient: "sea_level" | "vacuum" }, name: string, list: PropChoice[]): QuickSpec | null {
  const ox = list.find((p) => p.id === q.ox), fuel = list.find((p) => p.id === q.fuel);
  if (!ox || !fuel) return null;
  return { name, ox, fuel, thrust_N: q.thrust_N, pc_bar: q.pc_bar, of_ratio: q.of_ratio, ambient: q.ambient };
}

export function NewDesignDialog({ ws, pid, designs, onClose, onCreated, initial }: {
  ws: Workspace; pid: string; designs: DesignSummary[]; onClose(): void; onCreated(d: DesignFull): void; initial?: Design;
}) {
  const catalog = useCatalog((s) => s.catalog);
  const scratch = readScratch();
  const [start, setStart] = useState<Start>(initial ? "estimate" : "quick");
  const [name, setName] = useState(initial?.engine ?? "");
  const [quick, setQuick] = useState<{ ox: string; fuel: string; thrust_N: number; pc_bar: number; of_ratio: number | null; ambient: "sea_level" | "vacuum" }>(DEFAULT_QUICK);
  const [copyFrom, setCopyFrom] = useState(designs[0]?.id ?? "");
  const [fileDesign, setFileDesign] = useState<{ design: Design; note: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (start === "copy" && !name && designs[0]) setName(`${designs[0].name} B`); }, [start]); // eslint-disable-line react-hooks/exhaustive-deps

  const readFile = async (f: File) => {
    try {
      const r = await yaml.parse(await f.text());
      setFileDesign({ design: r.design, note: r.valid ? `${f.name} — valid engine design` : `${f.name} — imported with ${r.errors.length} issue(s) to fix` });
      if (!name) setName(f.name.replace(/\.(ya?ml)$/i, ""));
    } catch (e) { toast((e as Error).message, "bad"); }
  };

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      let d: DesignFull;
      const author = authorName();
      if (start === "copy") {
        d = await ws.createDesign(pid, { name: name.trim(), author, derived_from: { design_id: copyFrom } });
      } else {
        let config: Design | null = null;
        if (start === "estimate") config = initial ?? scratch;
        else if (start === "file") config = fileDesign?.design ?? null;
        else {
          const spec = catalog && specFrom(quick, name.trim(), catalog.propellants);
          config = spec ? newDesign(spec) : null;
        }
        if (!config) throw new Error("Nothing to create the design from");
        config = { ...config, engine: config.engine && start !== "quick" ? config.engine : name.trim().replace(/[^A-Za-z0-9._-]+/g, "-").slice(0, 64) || "ENGINE" };
        d = await ws.createDesign(pid, { name: name.trim(), author, config });
      }
      onCreated(d);
    } catch (e) {
      toast((e as Error).message, "bad");
      setBusy(false);
    }
  };

  const options: { value: Start; label: string }[] = [
    { value: "quick", label: "Quick setup" },
    ...(designs.length ? [{ value: "copy" as Start, label: "Copy a design" }] : []),
    ...(initial || scratch ? [{ value: "estimate" as Start, label: "My quick estimate" }] : []),
    { value: "file", label: "YAML file" },
  ];

  return (
    <Dialog wide title="New engine design" sub="One engine design = one complete configuration. You can change everything later." onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !name.trim() || (start === "file" && !fileDesign)} onClick={create}>Create design</button></>}>
      <Field label="Design name">
        <input className="plain-input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Baseline 20 bar"
          onKeyDown={(e) => { if (e.key === "Enter") void create(); }} />
      </Field>
      <Field label="Start from">
        <Segmented full value={start} onChange={setStart} options={options} />
      </Field>
      {start === "quick" && <QuickSetup spec={quick} onChange={setQuick} />}
      {start === "copy" && (
        <Field label="Design to copy" hint="The copy remembers where it came from.">
          <Select value={copyFrom} onChange={setCopyFrom} options={designs.map((d) => ({ value: d.id, label: d.name }))} />
        </Field>
      )}
      {start === "estimate" && <Callout tone="info">Your current quick estimate{(initial ?? scratch)?.operating_point ? ` (${(initial ?? scratch)!.operating_point.thrust_N} N, ${(initial ?? scratch)!.operating_point.pc_bar} bar)` : ""} becomes a design in this project, with version history from here on.</Callout>}
      {start === "file" && (
        <div className="stack-sm">
          <input ref={fileRef} type="file" accept=".yaml,.yml" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void readFile(f); e.target.value = ""; }} />
          <button className="btn" onClick={() => fileRef.current?.click()}>Choose engine YAML file…</button>
          {fileDesign ? <Callout tone="ok">{fileDesign.note}</Callout> : <span className="field-hint">A self-contained engine file, e.g. <span className="mono">config_resolved.yaml</span> from a report folder or a design exported from RESA Studio.</span>}
        </div>
      )}
    </Dialog>
  );
}
