import { useMemo, useState } from "react";
import { ChartCard, LineChart } from "../../components/charts/Chart";
import { Field, Group, NumberInput, Select, Toggle } from "../../components/ui/controls";
import { Callout, Empty } from "../../components/ui/display";
import { Icon } from "../../components/ui/icons";
import { getPath } from "../../lib/design";
import { sig } from "../../lib/format";
import { useSession } from "../../lib/session";
import { useCatalog } from "../../lib/stores";
import { CalcError, Inputs, Progress, ResultsHead } from "./common";

const OUTPUTS: { key: string; label: string; unit: string; scale?: number; needs?: "cooling" }[] = [
  { key: "isp_s", label: "Specific impulse", unit: "s" },
  { key: "mdot_kg_s", label: "Propellant flow", unit: "kg/s" },
  { key: "throat_diameter_m", label: "Throat diameter", unit: "mm", scale: 1e3 },
  { key: "total_length_m", label: "Engine length", unit: "mm", scale: 1e3 },
  { key: "tc_K", label: "Chamber temperature", unit: "K" },
  { key: "q_max_W_m2", label: "Peak heat flux", unit: "MW/m²", scale: 1e-6 },
  { key: "Q_total_W", label: "Total heat load", unit: "kW", scale: 1e-3 },
  { key: "T_wall_max_K", label: "Hottest wall", unit: "K", needs: "cooling" },
  { key: "wall_margin_K", label: "Wall margin", unit: "K", needs: "cooling" },
  { key: "dp_bar", label: "Coolant pressure drop", unit: "bar", needs: "cooling" },
  { key: "outlet_T_K", label: "Coolant outlet", unit: "K", needs: "cooling" },
];

export function TradeSection() {
  const { config, trade, runTrade } = useSession();
  const catalog = useCatalog((s) => s.catalog);
  const params = (catalog?.trade_parameters ?? []).filter((p) => getPath(config, p.path.split(".").slice(0, -1)) != null);
  const [param, setParam] = useState(params[0]?.path ?? "operating_point.pc_bar");
  const current = getPath(config, param.split(".")) as number | null | undefined;
  const [lo, setLo] = useState<number | null>(null);
  const [hi, setHi] = useState<number | null>(null);
  const [steps, setSteps] = useState(9);
  const [withCooling, setWithCooling] = useState(false);
  const base = typeof current === "number" ? current : 10;
  const from = lo ?? Number((base * 0.5).toPrecision(3)), to = hi ?? Number((base * 1.5).toPrecision(3));
  const info = params.find((p) => p.path === param);
  const values = useMemo(() => {
    const n = Math.max(2, Math.min(25, steps));
    return Array.from({ length: n }, (_, i) => Number((from + ((to - from) * i) / (n - 1)).toPrecision(5)));
  }, [from, to, steps]);
  const run = () => void runTrade(param, values, withCooling ? ["heat_flux", "cooling"] : ["heat_flux"]);
  const r = trade.data;
  const rows = r?.rows.filter((x) => x.ok) ?? [];
  const failed = r?.rows.filter((x) => !x.ok) ?? [];
  const coolFailed = rows.filter((x) => typeof x.cooling_error === "string");
  const xs = rows.map((x) => x.value as number);
  const shown = OUTPUTS.filter((o) => rows.some((row) => typeof row[o.key] === "number"));

  return (
    <div className="ws-main">
      <Inputs title="Trade study" lede="Vary one input over a range and see how the key results respond — everything else stays as in this design.">
        <Group title="Vary" no="1">
          <Field label="Input">
            <Select value={param} onChange={(v) => { setParam(v); setLo(null); setHi(null); }}
              options={params.map((p) => ({ value: p.path, label: `${p.label}${p.unit ? ` [${p.unit}]` : ""}` }))} />
          </Field>
          {typeof current !== "number" && <div className="field-hint">This input is currently automatic in the design; the study sets explicit values.</div>}
          <div className="grid-3">
            <Field label="From"><NumberInput value={from} onChange={setLo} unit={info?.unit} /></Field>
            <Field label="To"><NumberInput value={to} onChange={setHi} unit={info?.unit} /></Field>
            <Field label="Steps"><NumberInput value={steps} integer onChange={(v) => v && setSteps(v)} /></Field>
          </div>
          {config?.regen && <Toggle label="Include the cooling-channel solve (slower)" checked={withCooling} onChange={setWithCooling} />}
        </Group>
        <div style={{ padding: "4px 18px 20px" }}>
          <button className="btn btn-primary" style={{ width: "100%" }} disabled={trade.loading} onClick={run}><Icon name="play" size="sm" />Run study</button>
          <p className="field-hint" style={{ marginTop: 8 }}>{values.length} cases{withCooling ? " with channel solves" : ""}.</p>
        </div>
      </Inputs>
      <section className="ws-results">
        <Progress on={trade.loading} />
        <ResultsHead loading={trade.loading} />
        <CalcError error={trade.error} />
        {!r ? (trade.loading ? <div className="skeleton" style={{ height: 300 }} /> : <Empty title="Pick an input and run the study">
          Typical questions: how does chamber pressure trade throat size against heat flux? How many channels keep the wall below its limit?
        </Empty>) : (
          <>
            {coolFailed.length > 0 && <Callout tone="warn">Cooling solve failed for {coolFailed.map((f) => `${sig(f.value as number, 3)} (${f.cooling_error})`).join("; ")}</Callout>}
            {failed.length > 0 && <Callout tone="warn">{failed.length} case{failed.length > 1 ? "s" : ""} could not be computed: {failed.map((f) => `${sig(f.value as number, 3)} (${f.error})`).join("; ")}</Callout>}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
              {shown.map((o) => (
                <ChartCard key={o.key} title={o.label}>
                  <LineChart height={190} legend={false} xLabel={`${r.label}${r.unit ? ` [${r.unit}]` : ""}`} yLabel={`${o.unit}`}
                    xMarks={typeof current === "number" ? [{ x: current, label: "now" }] : []}
                    series={[{ id: o.key, label: o.label, color: o.needs ? "var(--s2)" : "var(--s1)", x: xs,
                      y: rows.map((row) => typeof row[o.key] === "number" ? (row[o.key] as number) * (o.scale ?? 1) : null), unit: o.unit }]} />
                </ChartCard>
              ))}
            </div>
            <section className="card" style={{ overflowX: "auto" }}>
              <table className="table">
                <thead><tr><th className="num">{r.label}<span className="unit">{r.unit || "–"}</span></th>{shown.map((o) => <th key={o.key} className="num">{o.label}<span className="unit">{o.unit}</span></th>)}</tr></thead>
                <tbody>{rows.map((row, i) => (
                  <tr key={i}><td className="num">{sig(row.value as number, 4)}</td>
                    {shown.map((o) => <td key={o.key} className="num">{typeof row[o.key] === "number" ? sig((row[o.key] as number) * (o.scale ?? 1), 4) : "—"}</td>)}</tr>
                ))}</tbody>
              </table>
            </section>
            <p className="muted" style={{ fontSize: 12 }}>{r.rows.length} cases in {sig(r.elapsed_s, 3)} s.</p>
          </>
        )}
      </section>
    </div>
  );
}
