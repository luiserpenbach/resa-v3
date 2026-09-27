import { Link } from "wouter";
import { EngineDrawing } from "../../components/charts/Drawing";
import { Disclosure, Field, Group, NumberField, SegField, Segmented, Select, SelectField, Toggle } from "../../components/ui/controls";
import { Callout, Kpi, Warnings } from "../../components/ui/display";
import { Icon } from "../../components/ui/icons";
import type { Design } from "../../lib/api";
import { DEFAULT_OF, matchPropellant, propellantBlock } from "../../lib/design";
import { fmt, sig } from "../../lib/format";
import { useSession, useValue } from "../../lib/session";
import { useCatalog } from "../../lib/stores";
import { useBase } from "../../lib/nav";
import { CalcError, InputProblems, Inputs, Progress, ResultsHead } from "./common";

export function PerformanceSection() {
  return (
    <div className="ws-main">
      <PerformanceInputs />
      <PerformanceResults />
    </div>
  );
}

function PerformanceInputs() {
  const config = useSession((s) => s.config)!;
  const update = useSession((s) => s.update);
  const replace = useSession((s) => s.replace);
  const perf = useSession((s) => s.perf.data);
  const catalog = useCatalog((s) => s.catalog);
  const analyze = !!config.analyze_point;
  const pt = analyze ? "analyze_point" : "operating_point";

  const setMode = (m: "design" | "analyze") => {
    if ((m === "analyze") === analyze) return;
    const c = { ...config };
    if (m === "analyze") {
      const g = perf?.geometry, p = perf?.performance;
      const op = config.operating_point ?? {};
      c.geometry = { throat_diameter_m: g?.throat_diameter_m ?? 0.03, eps: g?.eps ?? 4, exit_diameter_m: null };
      c.analyze_point = {
        mdot_ox_kg_s: p?.mdot_ox_kg_s ?? 1, mdot_fuel_kg_s: p?.mdot_fuel_kg_s ?? 0.25, eta_cstar: op.eta_cstar ?? 0.95,
        eta_cf: op.eta_cf ?? 0.98, p_amb_bar: op.p_amb_bar ?? 1.01325,
      };
      c.operating_point = null;
    } else {
      const p = perf?.performance;
      const ap = config.analyze_point ?? {};
      c.operating_point = {
        thrust_N: p?.thrust_N ?? 1000, pc_bar: p?.pc_bar ?? 20, eta_cstar: ap.eta_cstar ?? 0.95, eta_cf: ap.eta_cf ?? 0.98,
        p_amb_bar: ap.p_amb_bar ?? 1.01325, of_ratio: p ? Number(p.of_ratio.toFixed(3)) : null, eps: p ? Number(p.eps.toFixed(2)) : 10, pe_bar: null,
      };
      c.analyze_point = null;
      c.geometry = null;
    }
    replace(c);
  };

  const ox = catalog ? matchPropellant(catalog, config, "oxidizer") : undefined;
  const fuel = catalog ? matchPropellant(catalog, config, "fuel") : undefined;
  const setProp = (side: "oxidizer" | "fuel", id: string) => {
    if (!catalog) return;
    const pick = catalog.propellants.find((p) => p.id === id);
    const other = side === "oxidizer" ? fuel : ox;
    if (!pick || !other) return;
    const o = side === "oxidizer" ? pick : other, f = side === "fuel" ? pick : other;
    const block = { ...propellantBlock(o, f), fuel_temp_source: config.propellants?.fuel_temp_source, ox_temp_source: config.propellants?.ox_temp_source };
    let c: Design = { ...config, propellants: block };
    const of = DEFAULT_OF[`${o.id}/${f.id}`];
    if (!analyze && c.operating_point?.of_ratio != null && of) c = { ...c, operating_point: { ...c.operating_point, of_ratio: of } };
    if (c.regen?.solver) {
      // keep the coolant pointing at the same propellant side
      const side2 = c.regen.solver.coolant_side ?? "fuel";
      c = { ...c, regen: { ...c.regen, solver: { ...c.regen.solver, coolant: side2 === "fuel" ? block.fuel : block.oxidizer } } };
    }
    replace(c);
  };

  const pAmb = useValue<number>([pt, "p_amb_bar"]);
  const envMode = pAmb === 0 ? "vac" : Math.abs(pAmb - 1.01325) < 1e-4 ? "sl" : "custom";
  const eps = config.operating_point?.eps, pe = config.operating_point?.pe_bar;
  const expMode = eps != null ? "eps" : pe != null ? "pe" : "opt";
  const of = config.operating_point?.of_ratio;
  const pr = config.propellants ?? {};

  return (
    <Inputs title="Performance" lede="What the engine delivers and what it consumes. Change any value — results update as you type.">
      <div style={{ padding: "4px 18px 14px" }}>
        <Segmented full value={analyze ? "analyze" : "design"} onChange={setMode}
          options={[{ value: "design", label: "Size a new engine" }, { value: "analyze", label: "Check existing hardware" }]} />
      </div>
      <Group title="Propellants" no="1">
        <div className="grid-2">
          <Field label="Oxidizer" hint={ox ? `${pr.ox_phase ?? ox.phase} at ${fmt(pr.ox_temp_K, 0)} K` : pr.oxidizer}>
            <Select value={ox?.id ?? ""} onChange={(v) => setProp("oxidizer", v)}
              options={(catalog?.propellants ?? []).filter((p) => p.role === "oxidizer").map((p) => ({ value: p.id, label: p.label }))} />
          </Field>
          <Field label="Fuel" hint={fuel ? `${pr.fuel_phase ?? fuel.phase} at ${fmt(pr.fuel_temp_K, 0)} K` : pr.fuel}>
            <Select value={fuel?.id ?? ""} onChange={(v) => setProp("fuel", v)}
              options={(catalog?.propellants ?? []).filter((p) => p.role === "fuel").map((p) => ({ value: p.id, label: p.label }))} />
          </Field>
        </div>
        <Disclosure summary="Delivery conditions">
          <div className="grid-2">
            <NumberField path={["propellants", "ox_temp_K"]} label="Oxidizer temperature" unit="K" />
            <NumberField path={["propellants", "fuel_temp_K"]} label="Fuel temperature" unit="K" />
            <SegField path={["propellants", "ox_phase"]} label="Oxidizer phase" options={[{ value: "liquid", label: "Liquid" }, { value: "gas", label: "Gas" }]} />
            <SegField path={["propellants", "fuel_phase"]} label="Fuel phase" options={[{ value: "liquid", label: "Liquid" }, { value: "gas", label: "Gas" }]} />
          </div>
          <Toggle label="Use these delivery temperatures in the chemistry" checked={!!config.combustion?.use_delivery_temperatures}
            onChange={(v) => update(["combustion", "use_delivery_temperatures"], v)} />
        </Disclosure>
      </Group>

      {!analyze ? (
        <Group title="Operating point" no="2">
          <div className="grid-2">
            <NumberField path={["operating_point", "thrust_N"]} label="Thrust" unit="N" />
            <NumberField path={["operating_point", "pc_bar"]} label="Chamber pressure" unit="bar" />
          </div>
          <Field label="Mixture ratio (oxidizer / fuel)">
            <Segmented full value={of == null ? "best" : "set"} onChange={(v) => update(["operating_point", "of_ratio"], v === "best" ? null : Number((perf?.performance.of_ratio ?? DEFAULT_OF[`${ox?.id}/${fuel?.id}`] ?? 2).toFixed(2)))}
              options={[{ value: "best", label: "Best Isp" }, { value: "set", label: "Set value" }]} />
          </Field>
          {of != null ? <NumberField path={["operating_point", "of_ratio"]} label="O/F" unit="by mass" />
            : <div className="field-hint">Searching for the mixture ratio with the highest Isp{perf ? ` — found ${fmt(perf.performance.of_ratio, 2)}` : ""}.</div>}
        </Group>
      ) : (
        <Group title="Hardware & test flows" no="2" desc="Enter what you built and measured; RESA works out chamber pressure, thrust and Isp.">
          <NumberField path={["geometry", "throat_diameter_m"]} label="Throat diameter" unit="mm" scale={1e3} />
          <Field label="Nozzle exit given as">
            <Segmented full value={config.geometry?.eps != null ? "eps" : "d"}
              onChange={(v) => replace({ ...config, geometry: v === "eps"
                ? { ...config.geometry, eps: perf?.geometry.eps ? Number(perf.geometry.eps.toFixed(2)) : 4, exit_diameter_m: null }
                : { ...config.geometry, exit_diameter_m: perf?.geometry.exit_diameter_m ?? 0.05, eps: null } })}
              options={[{ value: "eps", label: "Area ratio" }, { value: "d", label: "Exit diameter" }]} />
          </Field>
          {config.geometry?.eps != null ? <NumberField path={["geometry", "eps"]} label="Area ratio" sym="ε" />
            : <NumberField path={["geometry", "exit_diameter_m"]} label="Exit diameter" unit="mm" scale={1e3} />}
          <div className="grid-2">
            <NumberField path={["analyze_point", "mdot_ox_kg_s"]} label="Oxidizer flow" unit="kg/s" />
            <NumberField path={["analyze_point", "mdot_fuel_kg_s"]} label="Fuel flow" unit="kg/s" />
          </div>
        </Group>
      )}

      <Group title="Nozzle & environment" no="3">
        <Field label="Operates at">
          <Segmented full value={envMode} onChange={(v) => {
            if (v === "custom") return update([pt, "p_amb_bar"], 0.5);
            const vac = v === "vac";
            let c = { ...config, [pt]: { ...config[pt], p_amb_bar: vac ? 0 : 1.01325 } };
            if (vac && !analyze && expMode === "opt") c = { ...c, operating_point: { ...c.operating_point, eps: 50 } };
            replace(c);
          }} options={[{ value: "sl", label: "Sea level" }, { value: "vac", label: "Vacuum" }, { value: "custom", label: "Other" }]} />
        </Field>
        {envMode === "custom" && <NumberField path={[pt, "p_amb_bar"]} label="Ambient pressure" unit="bar" />}
        {!analyze && (
          <>
            <Field label="Nozzle size set by">
              <Segmented full value={expMode} onChange={(v) => {
                const op = { ...config.operating_point, eps: null, pe_bar: null };
                if (v === "eps") op.eps = perf ? Number(perf.performance.eps.toFixed(1)) : 10;
                if (v === "pe") op.pe_bar = perf ? Number(Math.max(perf.performance.pe_bar, 0.01).toPrecision(3)) : 0.8;
                replace({ ...config, operating_point: op });
              }} options={[
                { value: "opt", label: "Ideal for ambient", hint: "exit pressure = ambient pressure" },
                { value: "eps", label: "Area ratio" },
                { value: "pe", label: "Exit pressure" },
              ]} />
            </Field>
            {expMode === "opt" && pAmb === 0 && <Callout tone="warn">In vacuum there is no ideal expansion — choose an area ratio or exit pressure.</Callout>}
            {expMode === "eps" && <NumberField path={["operating_point", "eps"]} label="Area ratio (exit / throat)" sym="ε" />}
            {expMode === "pe" && <NumberField path={["operating_point", "pe_bar"]} label="Exit pressure" unit="bar" />}
          </>
        )}
      </Group>

      <Group title="Losses" no="4" desc="How close the real engine comes to ideal chemistry and nozzle flow.">
        <div className="grid-2">
          <NumberField path={[pt, "eta_cstar"]} label="Combustion efficiency" sym="ηc*" hint="0.92–0.98 typical" />
          <NumberField path={[pt, "eta_cf"]} label="Nozzle efficiency" sym="ηCF" disabled={config[pt]?.eta_cf_source === "estimate"}
            hint={config[pt]?.eta_cf_source === "estimate" ? `estimated: ${perf ? fmt(perf.performance.eta_cf, 3) : "…"}` : "0.95–0.99 typical"} />
        </div>
        <Toggle label="Estimate nozzle efficiency from divergence & friction losses" checked={config[pt]?.eta_cf_source === "estimate"}
          onChange={(v) => update([pt, "eta_cf_source"], v ? "estimate" : "input")} />
        <Disclosure summary="Uncertainty">
          <NumberField path={[pt, "eta_cstar_tol"]} label="Combustion efficiency ±" nullable placeholder="none" hint="Adds a best/worst-case band to Isp and chamber pressure." />
        </Disclosure>
      </Group>

      <Group title="Chemistry model" no="5">
        <SelectField path={["combustion", "nozzle_flow"]} label="Gas behaviour in the nozzle" options={[
          { value: "equilibrium", label: "Shifting equilibrium (upper bound)" },
          { value: "frozen_at_throat", label: "Frozen after the throat" },
          { value: "frozen", label: "Frozen from the chamber (lower bound)" },
          { value: "single_gamma", label: "Simple — constant γ" },
        ]} hint="Real engines sit between frozen and equilibrium; low chamber pressure and small engines freeze early." />
        <Disclosure summary="Calculation engine">
          <SelectField path={["combustion", "backend"]} label="Chemistry source" options={[
            { value: "cea", label: "NASA CEA (built in)" },
            { value: "rocketcea", label: "RocketCEA (if installed)" },
            ...(config.combustion?.table ? [{ value: "table", label: "Table from file" }] : []),
          ]} />
        </Disclosure>
      </Group>
    </Inputs>
  );
}

function PerformanceResults() {
  const { perf, heat, errors } = useSession();
  const base = useBase();
  const r = perf.data;
  const p = r?.performance, g = r?.geometry;
  const band = p?.band;
  return (
    <section className="ws-results">
      <Progress on={perf.loading} />
      <ResultsHead loading={perf.loading} stale={perf.stale && !perf.loading && errors.length > 0} />
      <InputProblems />
      <CalcError error={perf.error} />
      {!r ? <div className="skeleton" style={{ height: 240 }} /> : (
        <>
          <div className="kpis">
            <Kpi hero label={p!.p_amb_bar === 0 ? "Specific impulse, vacuum" : Math.abs(p!.p_amb_bar - 1.01325) < 1e-3 ? "Specific impulse, sea level" : `Specific impulse at ${sig(p!.p_amb_bar, 3)} bar`} value={fmt(p!.isp_s, 1)} unit="s" tone="hot"
              sub={band ? `${fmt(band.isp_lo_s, 1)} – ${fmt(band.isp_hi_s, 1)} s with ±${band.eta_tol} efficiency` : undefined} />
            {p!.isp_vac_s != null && p!.p_amb_bar !== 0 && <Kpi label="Isp in vacuum" value={fmt(p!.isp_vac_s, 1)} unit="s" />}
            <Kpi label={r.mode === "analyze" ? "Thrust (calculated)" : "Thrust"} value={sig(p!.thrust_N, 4)} unit="N" />
            <Kpi label={r.mode === "analyze" ? "Chamber pressure (calculated)" : "Chamber pressure"} value={fmt(p!.pc_bar, 2)} unit="bar"
              sub={band ? `${fmt(band.pc_lo_bar, 2)} – ${fmt(band.pc_hi_bar, 2)} bar` : undefined} />
            <Kpi label="Mixture ratio O/F" value={fmt(p!.of_ratio, 2)} sub={r.provenance.of_ratio?.startsWith("optim") ? "best Isp" : undefined} />
            <Kpi label="Total propellant flow" value={sig(p!.mdot_total_kg_s, 4)} unit="kg/s" />
            <Kpi label="Oxidizer flow" value={sig(p!.mdot_ox_kg_s, 4)} unit="kg/s" />
            <Kpi label="Fuel flow" value={sig(p!.mdot_fuel_kg_s, 4)} unit="kg/s" />
            <Kpi label="Throat diameter" value={sig(g!.throat_diameter_m * 1e3, 4)} unit="mm" />
            <Kpi label="Exit diameter" value={sig(g!.exit_diameter_m * 1e3, 4)} unit="mm" sub={`area ratio ${fmt(g!.eps, 1)}`} />
            <Kpi label="Chamber temperature" value={fmt(p!.tc_K, 0)} unit="K" />
            <Kpi label="Characteristic velocity c*" value={fmt(p!.cstar_m_s, 0)} unit="m/s" sub={`ideal ${fmt(p!.cstar_ideal_m_s, 0)} m/s`} />
            <Kpi label="Exit pressure" value={sig(p!.pe_bar, 3)} unit="bar" tone={p!.separated ? "bad" : undefined} sub={p!.separated ? "flow separation risk" : `exit Mach ${fmt(p!.exit_mach, 2)}`} />
          </div>

          <div className="split">
            <section className="card">
              <div className="card-head"><h3>Engine outline</h3><span className="sub">true scale</span><span className="spacer" />
                <Link href={`${base}/chamber`} className="btn btn-ghost btn-sm">Shape the chamber <Icon name="arrow" size="sm" /></Link></div>
              <div className="card-body">
                <EngineDrawing x={r.contour.x_m} r={r.contour.r_m} height={250} dims={{
                  chamber_d: g!.chamber_diameter_m, throat_d: g!.throat_diameter_m, exit_d: g!.exit_diameter_m,
                  chamber_len: g!.chamber_length_m, nozzle_len: g!.nozzle_length_m,
                }} />
              </div>
            </section>
            <div className="stack">
              {p!.nozzle_models && <NozzleModels models={p!.nozzle_models} />}
              {heat.data && (
                <Link href={`${base}/heat`} className="card card-pad" style={{ textDecoration: "none", display: "grid", gap: 4 }}>
                  <span className="eyebrow">Heat load preview</span>
                  <span style={{ fontSize: 13.5 }}>Peak wall heat flux <b className="mono" style={{ color: "var(--hot)" }}>{sig(heat.data.summary.q_max_W_m2 / 1e6, 3)} MW/m²</b>,
                    {" "}total <b className="mono">{sig(heat.data.summary.Q_total_W / 1e3, 3)} kW</b> into the walls.</span>
                  <span className="muted row" style={{ fontSize: 12, gap: 4 }}>See the heat load <Icon name="arrow" size="sm" /></span>
                </Link>
              )}
              <div className="card card-pad" style={{ fontSize: 12.5, display: "grid", gap: 4 }}>
                <span className="eyebrow">Chemistry used</span>
                <span>Oxidizer: {r.propellant_states.oxidizer}</span>
                <span>Fuel: {r.propellant_states.fuel}</span>
                <span className="muted">γ {fmt(p!.gamma, 3)} · molar mass {fmt(p!.mw_kg_kmol, 2)} kg/kmol · CF {fmt(p!.cf, 3)}</span>
              </div>
            </div>
          </div>
          <Warnings items={r.warnings} areas={["performance", "nozzle", "propellants", "chamber"]} />
        </>
      )}
    </section>
  );
}

const MODEL_LABEL: Record<string, string> = {
  equilibrium: "Shifting equilibrium", frozen_at_throat: "Frozen after throat", frozen: "Frozen from chamber", single_gamma: "Constant γ",
};

function NozzleModels({ models }: { models: Record<string, number | string | null> }) {
  const entries = (["equilibrium", "frozen_at_throat", "frozen", "single_gamma"] as const)
    .map((k) => [k, models[k]] as const).filter(([, v]) => typeof v === "number") as [string, number][];
  if (!entries.length) return null;
  const max = Math.max(...entries.map(([, v]) => v)), min = Math.min(...entries.map(([, v]) => v));
  const lo = min - (max - min) * 0.6 - 1;
  return (
    <section className="card card-pad" style={{ display: "grid", gap: 8 }}>
      <span className="eyebrow">Ideal vacuum Isp by nozzle model</span>
      {entries.map(([k, v]) => (
        <div key={k} style={{ display: "grid", gridTemplateColumns: "118px 1fr 52px", gap: 8, alignItems: "center", fontSize: 12 }}>
          <span style={{ fontWeight: k === models.selected ? 650 : 400 }}>{MODEL_LABEL[k]}</span>
          <span className="meter"><span style={{ width: `${((v - lo) / (max - lo)) * 100}%`, background: k === models.selected ? "var(--hot)" : "var(--ink-4)", borderRadius: 4 }} /></span>
          <span className="mono" style={{ textAlign: "right" }}>{fmt(v, 1)}</span>
        </div>
      ))}
      <span className="field-hint">Bars start at an offset to show the spread. The highlighted model drives the results.</span>
    </section>
  );
}
