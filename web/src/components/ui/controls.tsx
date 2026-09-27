// Form controls. Bound variants read/write the open design through the
// session store by config path; values are shown in display units
// (`scale`: stored SI value × scale = shown value).
import { ReactNode, useEffect, useId, useRef, useState } from "react";
import type { Path } from "../../lib/design";
import { errorAt, useSession, useValue } from "../../lib/session";
import { Icon } from "./icons";

// ─── field shell ─────────────────────────────────────────────────────────
export function Field({ label, sym, hint, error, children, htmlFor }: {
  label: ReactNode; sym?: string; hint?: ReactNode; error?: string; children: ReactNode; htmlFor?: string;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={htmlFor}>
        <span>{label}</span>
        {sym && <span className="sym">{sym}</span>}
      </label>
      {children}
      {error ? <div className="field-error">{error}</div> : hint ? <div className="field-hint">{hint}</div> : null}
    </div>
  );
}

// ─── numbers ─────────────────────────────────────────────────────────────
function decimalsOf(s: string): number {
  const m = s.trim().match(/\.(\d+)/);
  return m ? m[1].length : 0;
}

function toText(v: number | null | undefined, scale: number): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "";
  return String(Number((v * scale).toPrecision(10)));
}

export function NumberInput({ value, onChange, unit, scale = 1, placeholder, disabled, invalid, id, min, max, integer, onBlur }: {
  value: number | null | undefined; onChange(v: number | null): void; unit?: string; scale?: number;
  placeholder?: string; disabled?: boolean; invalid?: boolean; id?: string; min?: number; max?: number; integer?: boolean;
  onBlur?(): void;
}) {
  const [text, setText] = useState(() => toText(value, scale));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setText(toText(value, scale));
  }, [value, scale]);

  const commit = (s: string) => {
    const t = s.trim().replace(",", ".");
    if (t === "") { onChange(null); return; }
    const n = Number(t);
    if (!Number.isFinite(n)) return;
    let v = n / scale;
    if (integer) v = Math.round(v);
    onChange(v);
  };

  const nudge = (dir: 1 | -1, big: boolean) => {
    const cur = Number(text.replace(",", "."));
    if (!Number.isFinite(cur)) return;
    const d = decimalsOf(text);
    let step = Math.pow(10, -d) * (big ? 10 : 1);
    if (integer) step = big ? 10 : 1;
    let n = Number((cur + dir * step).toFixed(Math.max(d, 0)));
    if (min !== undefined) n = Math.max(n, min * scale);
    if (max !== undefined) n = Math.min(n, max * scale);
    const s = n.toFixed(integer ? 0 : d);
    setText(s);
    commit(s);
  };

  return (
    <div className={`input-wrap${invalid ? " invalid" : ""}${disabled ? " disabled" : ""}`}>
      <input
        id={id}
        inputMode="decimal"
        value={text}
        placeholder={placeholder}
        disabled={disabled}
        onFocus={() => (focused.current = true)}
        onBlur={() => { focused.current = false; setText(toText(value, scale)); onBlur?.(); }}
        onChange={(e) => { setText(e.target.value); commit(e.target.value); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp" || e.key === "ArrowDown") {
            e.preventDefault();
            nudge(e.key === "ArrowUp" ? 1 : -1, e.shiftKey);
          }
        }}
      />
      {unit && <span className="unit">{unit}</span>}
    </div>
  );
}

export function NumberField({ path, label, sym, hint, unit, scale = 1, placeholder, nullable, integer, min, max, disabled }: {
  path: Path; label: ReactNode; sym?: string; hint?: ReactNode; unit?: string; scale?: number; placeholder?: string;
  nullable?: boolean; integer?: boolean; min?: number; max?: number; disabled?: boolean;
}) {
  const id = useId();
  const value = useValue<number | null>(path);
  const update = useSession((s) => s.update);
  const error = useSession((s) => errorAt(s.errors, path));
  return (
    <Field label={label} sym={sym} hint={hint} error={error} htmlFor={id}>
      <NumberInput
        id={id}
        value={typeof value === "number" ? value : null}
        unit={unit}
        scale={scale}
        placeholder={placeholder}
        integer={integer}
        min={min}
        max={max}
        disabled={disabled}
        invalid={!!error}
        onChange={(v) => { if (v !== null || nullable) update(path, v); }}
      />
    </Field>
  );
}

// ─── choices ─────────────────────────────────────────────────────────────
export interface Option<T extends string | number | boolean | null> { value: T; label: ReactNode; hint?: string }

export function Segmented<T extends string | number | boolean | null>({ value, options, onChange, full }: {
  value: T; options: Option<NoInfer<T>>[]; onChange(v: NoInfer<T>): void; full?: boolean;
}) {
  return (
    <div className={`seg${full ? " full" : ""}`} role="radiogroup">
      {options.map((o) => (
        <button key={String(o.value)} type="button" role="radio" aria-checked={o.value === value}
          className={o.value === value ? "on" : ""} title={o.hint} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Select<T extends string>({ value, options, onChange, id, invalid, disabled }: {
  value: T | ""; options: Option<NoInfer<T>>[]; onChange(v: NoInfer<T>): void; id?: string; invalid?: boolean; disabled?: boolean;
}) {
  return (
    <div className={`input-wrap${invalid ? " invalid" : ""}${disabled ? " disabled" : ""}`}>
      <select id={id} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value as T)}>
        {value === "" && <option value="">Choose…</option>}
        {options.map((o) => <option key={String(o.value)} value={String(o.value)}>{typeof o.label === "string" ? o.label : String(o.value)}</option>)}
      </select>
    </div>
  );
}

export function SelectField<T extends string>({ path, label, hint, options, sym }: {
  path: Path; label: ReactNode; hint?: ReactNode; options: Option<T>[]; sym?: string;
}) {
  const id = useId();
  const value = useValue<T>(path);
  const update = useSession((s) => s.update);
  const error = useSession((s) => errorAt(s.errors, path));
  return (
    <Field label={label} sym={sym} hint={hint} error={error} htmlFor={id}>
      <Select id={id} value={(value ?? "") as T | ""} options={options} invalid={!!error} onChange={(v) => update(path, v)} />
    </Field>
  );
}

export function SegField<T extends string | number | boolean | null>({ path, label, hint, options, full = true }: {
  path: Path; label: ReactNode; hint?: ReactNode; options: Option<T>[]; full?: boolean;
}) {
  const value = useValue<T>(path);
  const update = useSession((s) => s.update);
  const error = useSession((s) => errorAt(s.errors, path));
  return (
    <Field label={label} hint={hint} error={error}>
      <Segmented value={value} options={options} full={full} onChange={(v) => update(path, v)} />
    </Field>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange(v: boolean): void; label: ReactNode; disabled?: boolean }) {
  return (
    <label className="toggle" style={disabled ? { opacity: 0.5 } : undefined}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
      <span>{label}</span>
    </label>
  );
}

export function ToggleField({ path, label, hint }: { path: Path; label: ReactNode; hint?: ReactNode }) {
  const value = useValue<boolean>(path);
  const update = useSession((s) => s.update);
  return (
    <div className="field">
      <Toggle checked={!!value} onChange={(v) => update(path, v)} label={label} />
      {hint && <div className="field-hint">{hint}</div>}
    </div>
  );
}

export function TextField({ path, label, hint, placeholder }: { path: Path; label: ReactNode; hint?: ReactNode; placeholder?: string }) {
  const id = useId();
  const value = useValue<string>(path);
  const update = useSession((s) => s.update);
  const error = useSession((s) => errorAt(s.errors, path));
  return (
    <Field label={label} hint={hint} error={error} htmlFor={id}>
      <div className={`input-wrap${error ? " invalid" : ""}`}>
        <input id={id} className="text" value={value ?? ""} placeholder={placeholder} onChange={(e) => update(path, e.target.value)} />
      </div>
    </Field>
  );
}

// ─── structure ───────────────────────────────────────────────────────────
export function Group({ title, no, desc, children, aside }: { title: ReactNode; no?: string; desc?: ReactNode; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="group">
      <div className="group-title">
        {no && <span className="num-badge">{no}</span>}
        <h3>{title}</h3>
        <span className="spacer" />
        {aside}
      </div>
      {desc && <p className="group-desc">{desc}</p>}
      <div className="stack">{children}</div>
    </section>
  );
}

export function Disclosure({ summary, children, defaultOpen }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  return (
    <details className="disclosure" open={defaultOpen}>
      <summary><Icon name="chevron" size="sm" className="chev" />{summary}</summary>
      <div className="disclosure-body">{children}</div>
    </details>
  );
}

export function Tabs<T extends string>({ value, options, onChange }: { value: T; options: Option<NoInfer<T>>[]; onChange(v: NoInfer<T>): void }) {
  return (
    <div className="tabs" role="tablist">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={o.value === value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
