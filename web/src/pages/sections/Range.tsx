import { useEffect, useState } from "react";
import { ChartCard, Heatmap, LineChart } from "../../components/charts/Chart";
import { Field, Group, NumberInput, Segmented, Toggle } from "../../components/ui/controls";
import { Callout, Empty, Kpi } from "../../components/ui/display";
import { Icon } from "../../components/ui/icons";
import { fmt, sig } from "../../lib/format";
import { useSession, useValue } from "../../lib/session";
import { CalcError, InputProblems, Inputs, Progress, ResultsHead } from "./common";

const DEFAULTS = {
  ox_throttle: { ox_fraction: [0.5, 1.15], n: 25 },
  of_sweep: { of_range: [0.6, 1.6], n: 30 },   // × nominal O/F, resolved on enable
  envelope: { throttle_fraction: [0.6, 1.15], of_range: [0.7, 1.4], n: [18, 18] },
};

export function RangeSection() {
  return (
    <div className="ws-main">
      <RangeInputs />
      <RangeResults />
    </div>
  );
}

function PairField({ path, label, unit, scale = 1 }: { path: (string | number)[]; label: string; unit?: string; scale?: number }) {
  const v = useValue<number[]>(path);
  const update = useSession((s) => s.update);
  if (!v) return null;
  return (
    <Field label={label}>
      <div className="grid-2">
        <NumberInput value={v[0]} unit={unit} scale={scale} onChange={(x) => x !== null && update(path, [x, v[1]])} />
        <NumberInput value={v[1]} unit={unit} scale={scale} onChange={(x) => x !== null && update(path, [v[0], x])} />
      </div>
    </Field>
  );
}

function RangeInputs() {
  const { config, perf, update, runRange, range } = useSession();
  const od = config?.offdesign ?? null;
  const of0 = perf.data?.performance.of_ratio ?? 3;
  const toggle = (key: keyof typeof DEFAULTS, on: boolean) => {
    const cur = { ox_throttle: null, of_sweep: null, envelope: null, ...(od ?? {}) } as Record<string, unknown>;
    if (on) {
      const d = structuredClone(DEFAULTS[key]) as Record<string, unknown>;
      if (key === "of_sweep") d.of_range = [Number((of0 * 0.6).toFixed(2)), Number((of0 * 1.6).toFixed(2))];
      if (key === "envelope") d.of_range = [Number((of0 * 0.7).toFixed(2)), Number((of0 * 1.4).toFixed(2))];
      cur[key] = d;
    } else cur[key] = null;
    const any = Object.values(cur).some(Boolean);
    update(["offdesign"], any ? cur : null);
  };
  return (
    <Inputs title="Operating range" lede="How the engine behaves when you throttle it or shift the mixture ratio — same hardware, different flows.">
      <Group title="Throttle with oxidizer only" no="1" desc="Fuel flow fixed, oxidizer valve opened and closed (typical for pressure-fed tests).">
        <Toggle label="Include" checked={!!od?.ox_throttle} onChange={(v) => toggle("ox_throttle", v)} />
        {od?.ox_throttle && <>
          <PairField path={["offdesign", "ox_throttle", "ox_fraction"]} label="Oxidizer flow from / to" unit="%" scale={100} />
        </>}
      </Group>
      <Group title="Mixture ratio sweep" no="2" desc="Total flow fixed, O/F varied.">
        <Toggle label="Include" checked={!!od?.of_sweep} onChange={(v) => toggle("of_sweep", v)} />
        {od?.of_sweep && <PairField path={["offdesign", "of_sweep", "of_range"]} label="O/F from / to" />}
      </Group>
      <Group title="Throttle map" no="3" desc="Every combination of total flow and O/F — shows where the nozzle would separate.">
        <Toggle label="Include" checked={!!od?.envelope} onChange={(v) => toggle("envelope", v)} />
        {od?.envelope && <>
          <PairField path={["offdesign", "envelope", "throttle_fraction"]} label="Total flow from / to" unit="%" scale={100} />
          <PairField path={["offdesign", "envelope", "of_range"]} label="O/F from / to" />
        </>}
      </Group>
      <div style={{ padding: "4px 18px 20px" }}>
        <button className="btn btn-primary" style={{ width: "100%" }} disabled={!od || range.loading} onClick={() => void runRange()}>
          <Icon name="play" size="sm" />{range.data ? "Recalculate" : "Calculate operating range"}
        </button>
      </div>
    </Inputs>
  );
}

function RangeResults() {
  const { range, config, runRange, errors } = useSession();
  const [z, setZ] = useState<"thrust" | "isp" | "pc">("thrust");
  useEffect(() => {
    if (config?.offdesign && !range.data && !range.loading && !errors.length) void runRange();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const r = range.data;
  if (!config?.offdesign) {
    return (
      <section className="ws-results">
        <Empty title="Choose what to explore">Switch on a throttle sweep, a mixture-ratio sweep or the full throttle map on the left.</Empty>
      </section>
    );
  }
  const od = r?.ok ? r.offdesign : null;
  const n = r?.nominal;
  return (
    <section className="ws-results">
      <Progress on={range.loading} />
      <ResultsHead loading={range.loading} stale={range.stale}>
        {range.stale && !range.loading && <button className="btn btn-sm" onClick={() => void runRange()}><Icon name="restore" size="sm" />Update</button>}
      </ResultsHead>
      <InputProblems />
      <CalcError error={range.error} />
      {!od ? (range.loading ? <div className="skeleton" style={{ height: 300 }} /> : null) : (
        <>
          {n && <div className="kpis">
            <Kpi label="Nominal thrust" value={sig(n.thrust_N, 4)} unit="N" />
            <Kpi label="Nominal Isp" value={fmt(n.isp_s, 1)} unit="s" />
            <Kpi label="Nominal O/F" value={fmt(n.of_ratio, 2)} />
            <Kpi label="Nominal chamber pressure" value={fmt(n.pc_bar, 2)} unit="bar" />
          </div>}
          {od.ox_throttle && (
            <div className="split">
              <ChartCard title="Thrust when throttling the oxidizer">
                <LineChart height={240} xLabel="Oxidizer flow [kg/s]" yLabel="Thrust [N]" legend={false}
                  series={[{ id: "f", label: "Thrust", color: "var(--s1)", x: od.ox_throttle.mdot_ox_kg_s, y: od.ox_throttle.thrust_N, unit: "N" }]} />
              </ChartCard>
              <ChartCard title="Mixture ratio and Isp while throttling">
                <LineChart height={240} xLabel="Oxidizer flow [kg/s]" yLabel="Isp [s]" legend={false}
                  series={[{ id: "isp", label: "Isp", color: "var(--s2)", x: od.ox_throttle.mdot_ox_kg_s, y: od.ox_throttle.isp_s, unit: "s" }]} />
              </ChartCard>
            </div>
          )}
          {od.of_sweep && (
            <ChartCard title="Isp versus mixture ratio" sub="total flow held constant">
              <LineChart height={260} xLabel="Mixture ratio O/F" yLabel="Isp [s]" legend={false}
                xMarks={n ? [{ x: n.of_ratio, label: "design" }] : []}
                series={[{ id: "isp", label: "Isp", color: "var(--s1)", x: od.of_sweep.of, y: od.of_sweep.isp_s, unit: "s" }]} />
            </ChartCard>
          )}
          {od.envelope && (
            <ChartCard title="Throttle map" sub="hatched cells: nozzle flow separation risk"
              actions={<Segmented value={z} onChange={setZ} options={[{ value: "thrust", label: "Thrust" }, { value: "isp", label: "Isp" }, { value: "pc", label: "Pressure" }]} />}>
              <Heatmap height={320} x={od.envelope.throttle_frac.map((v) => v * 100)} y={od.envelope.of}
                z={z === "thrust" ? od.envelope.thrust_N : z === "isp" ? od.envelope.isp_s : od.envelope.pc_bar}
                mask={od.envelope.separated} xLabel="Total flow [% of nominal]" yLabel="Mixture ratio O/F"
                zLabel={z === "thrust" ? "Thrust" : z === "isp" ? "Isp" : "Chamber pressure"} zUnit={z === "thrust" ? "N" : z === "isp" ? "s" : "bar"}
                marker={n ? { x: 100, y: n.of_ratio } : undefined} />
            </ChartCard>
          )}
          {od.notes.length > 0 && <Callout tone="info">{od.notes.join(" ")}</Callout>}
        </>
      )}
    </section>
  );
}
