import { Link } from "wouter";
import { ChartCard, LineChart } from "../../components/charts/Chart";
import { EngineDrawing } from "../../components/charts/Drawing";
import { Field, Group, NumberField, NumberInput, SegField, Toggle } from "../../components/ui/controls";
import { Callout, Kpi, Warnings } from "../../components/ui/display";
import { Icon } from "../../components/ui/icons";
import type { CoolantCapacity } from "../../lib/api";
import { fmt, sig } from "../../lib/format";
import { useBase } from "../../lib/nav";
import { useSession } from "../../lib/session";
import { CalcError, InputProblems, Inputs, Progress, ResultsHead } from "./common";

export function HeatSection() {
  return (
    <div className="ws-main">
      <HeatInputs />
      <HeatResults />
    </div>
  );
}

function HeatInputs() {
  const { wallTemp, setWallTemp, config, update } = useSession();
  const film = config?.film_cooling;
  const needsOf = !!config?.operating_point && config.operating_point.of_ratio == null;
  return (
    <Inputs title="Heat load" lede="Hand-calc level: Bartz heat transfer from the hot gas into a wall held at one assumed temperature. No channels needed yet.">
      <Group title="Assumptions" no="1">
        <Field label="Hot-wall temperature" hint="The gas-side wall temperature you are designing for. Lower wall → more heat flux.">
          <div className="row">
            <input className="slider" type="range" min={300} max={1600} step={10} value={wallTemp} onChange={(e) => setWallTemp(Number(e.target.value))} />
            <div style={{ width: 110 }}><NumberInput value={wallTemp} unit="K" onChange={(v) => v && v > 100 && v < 4000 && setWallTemp(v)} /></div>
          </div>
        </Field>
        <NumberField path={["chamber", "bartz_correction"]} label="Heat-transfer factor" sym="× Bartz"
          hint="1.0 = textbook Bartz. Test data on small engines often lands at 0.6–0.8." />
        <NumberField path={["chamber", "bartz_correction_tol"]} label="Factor uncertainty ±" nullable placeholder="none"
          hint="Shows a band — useful until you have hot-fire calibration." />
      </Group>
      <Group title="Film cooling" no="2" desc="Part of the propellant injected along the wall: less heat flux, some Isp loss.">
        <Toggle label="Use film cooling" checked={!!film} disabled={needsOf}
          onChange={(v) => update(["film_cooling"], v ? { fraction: 0.05, side: "fuel", effectiveness_length_m: 0.1, film_temp_K: 600 } : null)} />
        {needsOf && <div className="field-hint">Film cooling needs a set mixture ratio (Performance → Set value).</div>}
        {film && <>
          <div className="grid-2">
            <NumberField path={["film_cooling", "fraction"]} label="Share of total flow" unit="%" scale={100} />
            <SegField path={["film_cooling", "side"]} label="Film propellant" options={[{ value: "fuel", label: "Fuel" }, { value: "oxidizer", label: "Oxidizer" }]} />
          </div>
          <div className="grid-2">
            <NumberField path={["film_cooling", "effectiveness_length_m"]} label="Decay length" unit="mm" scale={1e3} hint="How far the film stays effective." />
            <NumberField path={["film_cooling", "film_temp_K"]} label="Film gas temperature" unit="K" />
          </div>
        </>}
      </Group>
    </Inputs>
  );
}

function HeatResults() {
  const { heat, perf, errors, config } = useSession();
  const base = useBase();
  const h = heat.data;
  const s = h?.summary;
  const x = h ? h.profiles.x_m.map((v) => v * 1e3) : [];
  const Q = s ? s.Q_total_W : 0;
  return (
    <section className="ws-results">
      <Progress on={heat.loading || perf.loading} />
      <ResultsHead loading={heat.loading} stale={heat.stale && errors.length > 0} />
      <InputProblems />
      <CalcError error={heat.error ?? perf.error} />
      {!h || !s ? <div className="skeleton" style={{ height: 300 }} /> : (
        <>
          <div className="kpis">
            <Kpi hero tone="hot" label="Peak heat flux" value={sig(s.q_max_W_m2 / 1e6, 3)} unit="MW/m²"
              sub={`${Math.abs(s.x_q_max_m * 1e3) < 2 ? "at the throat" : `${fmt(s.x_q_max_m * 1e3, 1)} mm from the throat`}`} />
            <Kpi label="Total heat into the wall" value={sig(Q / 1e3, 4)} unit="kW" sub={`${fmt((s.Q_chamber_W / Q) * 100, 0)} % chamber · ${fmt((s.Q_nozzle_W / Q) * 100, 0)} % nozzle`} />
            <Kpi label="Throat heat flux" value={sig(s.q_throat_W_m2 / 1e6, 3)} unit="MW/m²" />
            <Kpi label="Gas recovery temperature (throat)" value={fmt(s.t_aw_throat_K, 0)} unit="K" />
            <Kpi label="Hot-gas wetted area" value={sig(s.wetted_area_m2 * 1e4, 4)} unit="cm²" />
            <Kpi label="Heat load per thrust" value={sig(Q / (perf.data?.performance.thrust_N || 1), 3)} unit="W/N" />
          </div>

          <ChartCard title="Heat flux along the engine" sub={`wall at ${fmt(h.wall_temp_K, 0)} K · x = 0 at the throat`}>
            <LineChart height={290} xLabel="Axial position [mm]" yLabel="Heat flux [MW/m²]" zeroY
              silhouette={{ x, r: h.profiles.r_m }}
              xMarks={[{ x: 0, label: "throat" }]}
              series={[{
                id: "q", label: "Heat flux", color: "var(--s1)", x, y: h.profiles.q_W_m2.map((v) => v / 1e6), unit: "MW/m²",
                band: h.profiles.q_lo_W_m2 && h.profiles.q_hi_W_m2
                  ? { lo: h.profiles.q_lo_W_m2.map((v) => v / 1e6), hi: h.profiles.q_hi_W_m2.map((v) => v / 1e6) } : undefined,
              }]} />
          </ChartCard>

          <div className="split">
            <ChartCard title="Where the heat goes in" sub="wall tinted by local flux">
              <EngineDrawing x={perf.data?.contour.x_m ?? h.profiles.x_m} r={perf.data?.contour.r_m ?? h.profiles.r_m} height={200}
                heat={{ x: h.profiles.x_m, q: h.profiles.q_W_m2 }} animate={false} />
              <div className="meter" style={{ marginTop: 10, height: 10 }} title="Chamber vs nozzle share">
                <span style={{ width: `${(s.Q_chamber_W / Q) * 100}%`, background: "var(--s1)" }} />
                <span style={{ width: 2, background: "var(--surface)" }} />
                <span style={{ flex: 1, background: "var(--s4)" }} />
              </div>
              <div className="legend" style={{ marginTop: 6 }}>
                <span className="li"><span className="sw" style={{ background: "var(--s1)" }} />chamber {sig(s.Q_chamber_W / 1e3, 3)} kW</span>
                <span className="li"><span className="sw" style={{ background: "var(--s4)" }} />nozzle {sig(s.Q_nozzle_W / 1e3, 3)} kW</span>
              </div>
            </ChartCard>
            <ChartCard title="Hot-gas recovery temperature">
              <LineChart height={200} xLabel="Axial position [mm]" yLabel="Temperature [K]" legend={false}
                series={[{ id: "taw", label: "Recovery temperature", color: "var(--s1)", x, y: h.profiles.t_aw_K, unit: "K", digits: 4 }]}
                refLines={[{ y: h.wall_temp_K, label: `assumed wall ${fmt(h.wall_temp_K, 0)} K`, color: "var(--ink-3)" }]} />
            </ChartCard>
          </div>

          <section>
            <div className="results-head"><h3>Can the propellant absorb it?</h3></div>
            <p className="muted" style={{ fontSize: 12.5, margin: "4px 0 10px" }}>
              If the whole heat load goes into one propellant flow (regenerative cooling), how warm does it get? Evaluated at {fmt(h.coolant_capacity[0]?.pressure_bar, 0)} bar coolant pressure.
            </p>
            <div className="grid-2">
              {h.coolant_capacity.map((c) => <CapacityCard key={c.side} c={c} />)}
            </div>
          </section>
          {!config?.regen && (
            <Link href={`${base}/cooling`} className="card card-pad row" style={{ textDecoration: "none" }}>
              <Icon name="channels" /><span><b>Next: design cooling channels</b><br /><span className="muted" style={{ fontSize: 12.5 }}>Get real wall temperatures, coolant pressure drop and the p–h path.</span></span>
              <span className="spacer" /><Icon name="arrow" />
            </Link>
          )}
          <Warnings items={perf.data?.warnings} areas={["cooling"]} />
        </>
      )}
    </section>
  );
}

function CapacityCard({ c }: { c: CoolantCapacity }) {
  const ok = c.outlet_T_K != null && !c.boils;
  const tone = c.note ? "warn" : ok ? "ok" : "bad";
  return (
    <div className="card cap-card">
      <h4><Icon name="drop" size="sm" />{c.side === "fuel" ? "Fuel" : "Oxidizer"} as coolant <span className="muted" style={{ fontWeight: 400 }}>· {c.fluid}</span></h4>
      {c.note ? <Callout tone="warn">No fluid property model for this propellant — the capacity cannot be checked.</Callout> : (
        <>
          <dl className="kv">
            <dt>Flow</dt><dd>{sig(c.mdot_kg_s, 4)}<span className="u">kg/s</span></dd>
            <dt>Enthalpy rise</dt><dd>{sig(c.dh_kJ_kg, 4)}<span className="u">kJ/kg</span></dd>
            <dt>Temperature in → out</dt><dd>{fmt(c.inlet_T_K, 0)} → {c.outlet_T_K != null ? fmt(c.outlet_T_K, 0) : "beyond fluid data"}<span className="u">K</span></dd>
            {c.t_sat_K != null && <><dt>Boiling point at this pressure</dt><dd>{fmt(c.t_sat_K, 0)}<span className="u">K</span></dd></>}
          </dl>
          <Callout tone={tone as "ok" | "bad" | "warn"}>
            {c.boils ? "The flow would boil — raise the coolant pressure above critical, cool with the other propellant, or add film cooling."
              : c.outlet_T_K == null ? "The heat load exceeds what this flow can carry within the fluid data range."
              : c.outlet_T_K > 900 ? "Very hot outlet — check coking/decomposition limits of this propellant."
              : "This flow can carry the heat load."}
          </Callout>
        </>
      )}
    </div>
  );
}
