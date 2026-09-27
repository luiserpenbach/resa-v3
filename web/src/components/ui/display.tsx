import { ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Warning } from "../../lib/api";
import { useToasts } from "../../lib/stores";
import { Icon } from "./icons";

export function Kpi({ label, value, unit, sub, tone, hero, title }: {
  label: ReactNode; value: ReactNode; unit?: string; sub?: ReactNode;
  tone?: "hot" | "cool" | "good" | "warn" | "bad"; hero?: boolean; title?: string;
}) {
  return (
    <div className={`kpi${tone ? ` ${tone}` : ""}${hero ? " kpi-hero" : ""}`} title={title}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value"><span className="v">{value}</span>{unit && <span className="u">{unit}</span>}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export function Callout({ tone = "info", children, icon }: { tone?: "info" | "warn" | "bad" | "ok"; children: ReactNode; icon?: string }) {
  return (
    <div className={`callout ${tone}`}>
      <Icon name={icon ?? (tone === "ok" ? "check" : tone === "info" ? "info" : "warn")} size="sm" />
      <div>{children}</div>
    </div>
  );
}

/** Backend warnings, softened: config keys become readable words. */
export function humanize(msg: string): string {
  return msg
    .replace(/combustion\.use_delivery_temperatures: true/g, "turn on “Use delivery temperatures” (Chemistry)")
    .replace(/combustion\.nozzle_flow/g, "the nozzle flow model")
    .replace(/eta_cf_source: estimate/g, "“Estimate nozzle efficiency”")
    .replace(/\beta_cf\b/g, "nozzle efficiency")
    .replace(/\beta_c\*/g, "combustion efficiency")
    .replace(/nozzle_flow=single_gamma/g, "Simple (constant γ) nozzle model")
    .replace(/propellants\.(ox|fuel)_temp_K/g, (_m, s) => `${s === "ox" ? "oxidizer" : "fuel"} delivery temperature`)
    .replace(/solver\.hot_gas\.[a-z_/]+/g, "hot-gas properties")
    .replace(/\bregen: /g, "")
    .replace(/(uncalibrated )?Bartz (factor|correction)/g, "$1heat-transfer factor")
    .replace(/at Bartz ([\d.]+)/g, "at heat-transfer factor $1")
    .replace(/\bpc\b/g, "chamber pressure")
    .replace(/\bp_amb\b/g, "ambient pressure");
}

export function Warnings({ items, areas }: { items: Warning[] | undefined; areas?: Warning["area"][] }) {
  const list = (items ?? []).filter((w) => !areas || areas.includes(w.area));
  if (!list.length) return null;
  return (
    <div className="warn-list">
      {list.map((w, i) => <Callout key={i} tone={/exceed|below|unachievable|SEPARATION|do not fit|cannot/i.test(w.message) ? "bad" : "warn"}>{humanize(w.message)}</Callout>)}
    </div>
  );
}

export function Spinner() { return <span className="spinner" aria-label="Working" />; }

export function Empty({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <div style={{ maxWidth: 460, lineHeight: 1.5 }}>{children}</div>}
      {action}
    </div>
  );
}

export function Dialog({ title, sub, children, footer, onClose, wide }: {
  title: ReactNode; sub?: ReactNode; children: ReactNode; footer?: ReactNode; onClose(): void; wide?: boolean;
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return createPortal(
    <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`dialog${wide ? " dialog-wide" : ""}`} role="dialog" aria-modal="true">
        <div className="dialog-head"><h2>{title}</h2>{sub && <p>{sub}</p>}</div>
        <div className="dialog-body">{children}</div>
        {footer && <div className="dialog-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ title, children, onClose, actions }: { title: ReactNode; children: ReactNode; onClose(): void; actions?: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return createPortal(
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true">
        <div className="drawer-head">
          <h2>{title}</h2><span className="spacer" />{actions}
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </>,
    document.body,
  );
}

export interface MenuItem { label: ReactNode; icon?: string; onClick(): void; danger?: boolean; divider?: boolean }

export function Menu({ trigger, items, align = "right" }: { trigger: (open: () => void) => ReactNode; items: MenuItem[]; align?: "left" | "right" }) {
  const [pos, setPos] = useState<{ top: number; left?: number; right?: number } | null>(null);
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!pos) return;
    const close = () => setPos(null);
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("click", close);
    window.addEventListener("keydown", k);
    return () => { window.removeEventListener("click", close); window.removeEventListener("keydown", k); };
  }, [pos]);
  const open = () => {
    const r = ref.current!.getBoundingClientRect();
    setTimeout(() => setPos(align === "right"
      ? { top: r.bottom + 6 + window.scrollY, right: window.innerWidth - r.right }
      : { top: r.bottom + 6 + window.scrollY, left: r.left }), 0);
  };
  return (
    <span ref={ref} style={{ display: "inline-flex" }}>
      {trigger(open)}
      {pos && createPortal(
        <div className="menu" style={{ top: pos.top, left: pos.left, right: pos.right }} onClick={(e) => e.stopPropagation()}>
          {items.map((it, i) => it.divider ? <hr key={i} /> : (
            <button key={i} className={it.danger ? "btn-danger" : ""} onClick={() => { setPos(null); it.onClick(); }}>
              {it.icon && <Icon name={it.icon} size="sm" />}{it.label}
            </button>
          ))}
        </div>, document.body)}
    </span>
  );
}

export function Toasts() {
  const items = useToasts((s) => s.items);
  return createPortal(
    <div className="toast-stack" aria-live="polite">
      {items.map((t) => <div key={t.id} className={`toast${t.tone === "bad" ? " bad" : ""}`}>{t.text}</div>)}
    </div>,
    document.body,
  );
}

export function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = { concept: "Concept", preliminary: "Preliminary", detailed: "Detailed", frozen: "Frozen" };
  return <span className={`badge status-${status}`}>{label[status] ?? status}</span>;
}
