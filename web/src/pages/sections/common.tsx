import { ReactNode } from "react";
import { Callout, Spinner } from "../../components/ui/display";
import { labelFor } from "../../lib/design";
import { useSession } from "../../lib/session";

export function Inputs({ title, lede, children }: { title: string; lede: ReactNode; children: ReactNode }) {
  return (
    <aside className="ws-inputs" aria-label={`${title} inputs`}>
      <div className="ws-inputs-head">
        <h2>{title}</h2>
        <p>{lede}</p>
      </div>
      {children}
    </aside>
  );
}

export function ResultsHead({ title = "Results", loading, stale, children }: { title?: string; loading?: boolean; stale?: boolean; children?: ReactNode }) {
  return (
    <div className="results-head">
      <h3>{title}</h3>
      {loading && <span className="row muted" style={{ gap: 6, fontSize: 12 }}><Spinner />updating</span>}
      {!loading && stale && <span className="muted" style={{ fontSize: 12 }}>showing previous result</span>}
      <span className="spacer" />
      {children}
    </div>
  );
}

/** Summary of input problems — the numbers on screen belong to the last valid inputs. */
export function InputProblems() {
  const errors = useSession((s) => s.errors);
  if (!errors.length) return null;
  return (
    <Callout tone="bad">
      <b>{errors.length === 1 ? "One input needs attention" : `${errors.length} inputs need attention`}</b> — results show the last valid state.
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
        {errors.slice(0, 6).map((e, i) => {
          const path = e.path.join(".");
          const label = path ? labelFor(path) : "Design";
          return <li key={i}><b>{label}:</b> {e.message}</li>;
        })}
      </ul>
    </Callout>
  );
}

export function CalcError({ error }: { error: string | null }) {
  if (!error) return null;
  return <Callout tone="bad"><b>The calculation stopped:</b> {error}</Callout>;
}

export function Progress({ on }: { on: boolean }) {
  return on ? <div className="progress-line" aria-hidden="true" /> : null;
}
