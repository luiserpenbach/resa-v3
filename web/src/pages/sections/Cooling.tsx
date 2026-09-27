import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { ChartCard, LineChart, PhChart, Series, Shade } from "../../components/charts/Chart";
import { CrossSection, ProfileInput, ProfileValue } from "../../components/charts/Profile";
import { Disclosure, Field, Group, NumberField, NumberInput, SegField, Segmented, Select, SelectField, Tabs, Toggle } from "../../components/ui/controls";
import { Callout, Empty, Kpi, Warnings } from "../../components/ui/display";
import { Icon } from "../../components/ui/icons";
import { calc, downloadBlob } from "../../lib/api";
import { ChannelDefaults, matchPropellant, regenBlock, suggestChannels } from "../../lib/design";
import { fmt, sig } from "../../lib/format";
import { sessionEpoch, useSession } from "../../lib/session";
import { toast, useCatalog } from "../../lib/stores";
import { EngineViewer } from "./Chamber";
import { CalcError, InputProblems, Inputs, Progress, ResultsHead } from "./common";

export function CoolingSection() {
  const hasRegen = useSession((s) => !!s.config?.regen);
  return (
    <div className="ws-main">
      {hasRegen ? <ChannelInputs /> : <SetupInputs />}
      {hasRegen ? <CoolingResults /> : <SetupPreview />}
    </div>
  );
}

// ─── first-time setup ─────────────────────────────────────────────────────
function SetupInputs() {
  const { config, perf, setCoolingNotes } = useSession();
  const catalog = useCatalog((s) => s.catalog);
  const suggested = useMemo(() => suggestChannels(config!, perf.data, catalog), [config, perf.data, catalog]);
  const [c, setC] = useState<ChannelDefaults>(suggested);
  const [searching, setSearching] = useState(false);
  useEffect(() => setC(suggested), [perf.data?.geometry.throat_diameter_m]); // eslint-disable-line react-hooks/exhaustive-deps
  const fuel = catalog ? matchPropellant(catalog, config!, "fuel") : undefined;
  const ox = catalog ? matchPropellant(catalog, config!, "oxidizer") : undefined;
  const pr = config?.propellants ?? {};
  // merge only the channel layout into the *current* design (the search takes seconds)
  const apply = (regen: Record<string, unknown>) => {
    const cur = useSession.getState().config;
    if (cur) useSession.getState().replace({ ...cur, regen, cooling: null });
  };
  const ctl = useRef<AbortController | null>(null);
  useEffect(() => () => ctl.current?.abort(), []);
  const create = () => {
    setCoolingNotes([]);
    apply(regenBlock(config!, c));
    toast("Channel layout created — solving…");
  };
  const assist = async () => {
    setSearching(true);
    const mine = sessionEpoch();
    ctl.current?.abort();
    ctl.current = new AbortController();
    try {
      const s = await calc.suggestChannels(config!, ctl.current.signal);
      if (mine !== sessionEpoch()) return;
      setCoolingNotes(s.notes);
      apply(s.regen);
      toast(`Layout found after ${s.trials.length} trial solve${s.trials.length === 1 ? "" : "s"}`);
    } catch (e) {
      if ((e as Error).name !== "AbortError" && mine === sessionEpoch()) toast((e as Error).message, "bad");
    } finally {
      setSearching(false);
    }
  };
  return (
    <Inputs title="Cooling channels" lede="Let RESA search for a first layout that works, or start from the values below. Every number can be refined afterwards, including profiles that vary along the engine.">
      <div style={{ padding: "0 18px 16px" }}>
        <button className="btn btn-hot btn-lg" style={{ width: "100%" }} onClick={assist} disabled={!perf.data || searching}>
          {searching ? <><span className="spinner" />Trying layouts…</> : <><Icon name="bolt" size="sm" />Find a layout that works</>}
        </button>
        <p className="field-hint" style={{ marginTop: 8 }}>
          Picks the coolant that can carry the heat, sizes channels for coolant speed, and solves a few variants
          (depth, width, inlet pressure) until the wall stays under its limit. Takes a few seconds.
        </p>
      </div>
      <Group title="Or start from these values" no="1">
        <Field label="Cool the chamber with">
          <Segmented full value={c.side} onChange={(side) => setC({ ...c, side, inlet_T_K: side === "fuel" ? pr.fuel_temp_K : pr.ox_temp_K })}
            options={[
              { value: "fuel", label: `Fuel${fuel ? ` · ${fuel.label.split(" (")[0]}` : ""}` },
              { value: "oxidizer", label: `Oxidizer${ox ? ` · ${ox.label.split(" (")[0]}` : ""}` },
            ]} />
        </Field>
        {((c.side === "fuel" && fuel && !fuel.can_cool) || (c.side === "oxidizer" && ox && !ox.can_cool)) &&
          <Callout tone="warn">No fluid property model for this propellant — pick the other one as coolant.</Callout>}
        <div className="grid-2">
          <Field label="Inlet pressure"><NumberInput value={c.inlet_p_bar} unit="bar" onChange={(v) => v && setC({ ...c, inlet_p_bar: v })} /></Field>
          <Field label="Inlet temperature"><NumberInput value={c.inlet_T_K} unit="K" onChange={(v) => v && setC({ ...c, inlet_T_K: v })} /></Field>
          <Field label="Number of channels"><NumberInput value={c.count} integer onChange={(v) => v && setC({ ...c, count: v })} /></Field>
          <Field label="Channel height"><NumberInput value={typeof c.height_m === "number" ? c.height_m : 0} unit="mm" scale={1e3} onChange={(v) => v && setC({ ...c, height_m: v })} /></Field>
          <Field label="Rib width"><NumberInput value={c.rib_m} unit="mm" scale={1e3} onChange={(v) => v && setC({ ...c, rib_m: v })} /></Field>
          <Field label="Hot-wall thickness"><NumberInput value={c.wall_m} unit="mm" scale={1e3} onChange={(v) => v && setC({ ...c, wall_m: v })} /></Field>
        </div>
        <Field label="Wall material">
          <Select value={c.material} onChange={(v) => setC({ ...c, material: v })}
            options={(catalog?.materials ?? []).map((m) => ({ value: m.name, label: `${m.name} — limit ${fmt(m.max_service_T_K, 0)} K` }))} />
        </Field>
        <button className="btn" onClick={create} disabled={!perf.data || searching}><Icon name="channels" size="sm" />Create with these values</button>
        {config?.cooling && <p className="field-hint">This design also has an older throat-only cooling block; it will be replaced by the full channel layout.</p>}
      </Group>
    </Inputs>
  );
}

function SetupPreview() {
  const heat = useSession((s) => s.heat.data);
  return (
    <section className="ws-results">
      <Empty title="No cooling channels yet">
        Set up a first channel layout on the left. RESA then marches the coolant through every channel, balancing the hot-gas heat flux
        against wall conduction and coolant-side heat transfer — you get wall temperatures against the material limit, pressure drop,
        and the coolant’s path on a pressure–enthalpy diagram.
        {heat && <p style={{ marginTop: 10 }}>For orientation: the walls take <b className="mono">{sig(heat.summary.Q_total_W / 1e3, 3)} kW</b> with a peak of <b className="mono">{sig(heat.summary.q_max_W_m2 / 1e6, 3)} MW/m²</b>.</p>}
      </Empty>
    </section>
  );
}

// ─── channel inputs ───────────────────────────────────────────────────────
function ChannelInputs() {
  const { config, perf, update, replace } = useSession();
  const catalog = useCatalog((s) => s.catalog);
  const regen = config!.regen;
  const sol = regen.solver ?? {};
  const pr = config!.propellants ?? {};
  const contour = perf.data?.contour;
  const xRange: [number, number] = contour ? [contour.x_m[0], contour.x_m[contour.x_m.length - 1]] : [-0.1, 0.1];
  const sil = contour ? { x: contour.x_m, r: contour.r_m } : undefined;
  const side: "fuel" | "oxidizer" = sol.coolant_side ?? "fuel";
  const coupled = side === "fuel" ? pr.fuel_temp_source === "regen_outlet" : pr.ox_temp_source === "regen_outlet";

  const setSide = (s2: "fuel" | "oxidizer") => {
    const c = { ...config!, regen: { ...regen, solver: { ...sol, coolant_side: s2, coolant: s2 === "fuel" ? pr.fuel : pr.oxidizer,
      coolant_correlation: /hydrogen/i.test(s2 === "fuel" ? pr.fuel : pr.oxidizer) ? "taylor" : (sol.coolant_correlation === "taylor" ? "auto" : sol.coolant_correlation),
      inlet: { ...sol.inlet, temperature_K: s2 === "fuel" ? pr.fuel_temp_K : pr.ox_temp_K } } },
      propellants: { ...pr, fuel_temp_source: "input", ox_temp_source: "input" } };
    replace(c);
  };
  const setCoupled = (v: boolean) => {
    replace({ ...config!, propellants: { ...pr, fuel_temp_source: v && side === "fuel" ? "regen_outlet" : "input",
      ox_temp_source: v && side === "oxidizer" ? "regen_outlet" : "input" } });
  };
  const profile = (path: (string | number)[], label: string, unit = "mm", scale = 1e3) => (
    <ProfileInput label={label} unit={unit} scale={scale} xRange={xRange} silhouette={sil}
      value={(useValueLoose(config!, path) ?? 0) as ProfileValue}
      onChange={(v) => {
        if (path.join(".") === "regen.channels.rib.width") {
          update(["regen", "channels", "rib"], { ...regen.channels.rib, mode: typeof v === "number" ? "fixed_width" : "variable", width: v });
        } else update(path, v);
      }} />
  );
  const fit = () => {
    const s = suggestChannels(config!, perf.data, catalog);
    update(["regen", "channels", "count"], s.count);
  };

  return (
    <Inputs title="Cooling channels" lede="Channels run along the wall from the nozzle to the injector. Wall temperature, pressure drop and the coolant path update as you edit.">
      <Group title="Coolant" no="1">
        <Field label="Cooling with">
          <Segmented full value={side} onChange={setSide} options={[{ value: "fuel", label: `Fuel · ${pr.fuel}` }, { value: "oxidizer", label: `Oxidizer · ${pr.oxidizer}` }]} />
        </Field>
        <div className="grid-2">
          <NumberField path={["regen", "solver", "inlet", "pressure_bar"]} label="Inlet pressure" unit="bar" />
          <NumberField path={["regen", "solver", "inlet", "temperature_K"]} label="Inlet temperature" unit="K" />
        </div>
        <SegField path={["regen", "solver", "inlet", "location"]} label="Coolant enters at" options={[
          { value: "nozzle_end", label: "Nozzle end (counter-flow)" }, { value: "injector_end", label: "Injector end" }]} />
        <Toggle label="Heated coolant feeds the injector" checked={coupled} onChange={setCoupled} />
        {coupled && <div className="field-hint">The {side} enters combustion at the channel outlet temperature (solved iteratively — slower).</div>}
        <Disclosure summary="More coolant options">
          <NumberField path={["regen", "solver", "coolant_fraction"]} label="Share of the propellant flow used" nullable placeholder="all of it" />
          <SelectField path={["regen", "solver", "coolant_correlation"]} label="Coolant heat-transfer model" options={[
            { value: "auto", label: "Automatic (turbulent / boiling / supercritical)" },
            { value: "gnielinski", label: "Gnielinski (single phase)" },
            { value: "taylor", label: "Taylor (gaseous hydrogen)" },
          ]} />
          <NumberField path={["regen", "solver", "roughness"]} label="Wall roughness" unit="µm" scale={1e6} hint="8–15 µm for as-printed metal (LPBF)." />
        </Disclosure>
      </Group>

      <Group title="Channel shape" no="2" aside={<button className="btn btn-ghost btn-sm" onClick={fit} title="Pick a count that suits the throat circumference">Fit count</button>}>
        <NumberField path={["regen", "channels", "count"]} label="Number of channels" integer />
        {profile(["regen", "channels", "height"], "Channel height")}
        {profile(["regen", "channels", "rib", "width"], "Rib width")}
        {profile(["regen", "channels", "inner_wall_thickness"], "Hot-wall thickness")}
        {profile(["regen", "channels", "helix", "profile"], "Spiral angle", "°", 1)}
        <Disclosure summary="Coverage & limits">
          <div className="grid-2">
            <NumberField path={["regen", "channels", "start_x"]} label="Channels start" unit="mm" scale={1e3} nullable placeholder="injector" />
            <NumberField path={["regen", "channels", "stop_x"]} label="Channels end" unit="mm" scale={1e3} nullable placeholder="nozzle exit" />
          </div>
          <div className="field-hint">Positions from the throat (negative = chamber side). Beyond the channel end the nozzle is radiation-cooled.</div>
          <NumberField path={["regen", "channels", "min_channel_width"]} label="Minimum printable channel width" unit="mm" scale={1e3} />
        </Disclosure>
      </Group>

      <Group title="Wall" no="3">
        <Field label="Material">
          <Select value={sol.wall?.material ?? ""} onChange={(v) => update(["regen", "solver", "wall", "material"], v)}
            options={(catalog?.materials ?? []).map((m) => ({ value: m.name, label: `${m.name} — limit ${fmt(m.max_service_T_K, 0)} K` }))} />
        </Field>
        <NumberField path={["regen", "solver", "wall", "max_wall_temp_K"]} label="Temperature limit" unit="K" nullable placeholder="material default" />
        <Toggle label="Check wall stress (thermal + pressure)" checked={sol.wall?.stress_check !== false}
          onChange={(v) => update(["regen", "solver", "wall", "stress_check"], v)} />
      </Group>

      <Group title="Uncooled nozzle extension" no="4" desc="Past the channel end the wall only radiates heat away.">
        <Toggle label="Model radiation cooling past the channels" checked={sol.skirt?.enabled !== false}
          onChange={(v) => update(["regen", "solver", "skirt", "enabled"], v)} />
        {sol.skirt?.enabled !== false && <div className="grid-2">
          <NumberField path={["regen", "solver", "skirt", "emissivity"]} label="Emissivity" />
          <NumberField path={["regen", "solver", "skirt", "T_env_K"]} label="Surroundings" unit="K" />
        </div>}
      </Group>

      <Group title="Solver" no="5">
        <NumberField path={["regen", "geometry", "n_stations"]} label="Stations along the engine (full solve)" integer />
        <button className="btn btn-ghost btn-sm btn-danger" style={{ justifySelf: "start" }}
          onClick={() => { if (confirm("Remove the cooling-channel layout from this design?")) update(["regen"], null); }}>Remove channel layout</button>
      </Group>
    </Inputs>
  );
}

function useValueLoose(obj: Record<string, unknown>, path: (string | number)[]): unknown {
  let o: unknown = obj;
  for (const k of path) o = (o as Record<string, unknown> | null)?.[k as string];
  return o;
}

// ─── results ──────────────────────────────────────────────────────────────
type Tab = "wall" | "coolant" | "geometry" | "structure";

function CoolingResults() {
  const { cool, perf, fidelity, setFidelity, errors } = useSession();
  const notes = useSession((st) => st.coolingNotes);
  const [tab, setTab] = useState<Tab>("wall");
  const r = cool.data;
  const s = r?.ok ? r.summary : null;
  return (
    <section className="ws-results">
      <Progress on={cool.loading || perf.loading} />
      <ResultsHead loading={cool.loading} stale={cool.stale && errors.length > 0}>
        <Segmented value={fidelity} onChange={setFidelity} options={[
          { value: "preview", label: "Fast", hint: "~90 stations while you edit" }, { value: "full", label: "Full resolution" }]} />
      </ResultsHead>
      <InputProblems />
      <CalcError error={cool.error ?? perf.error} />
      {!s || !r ? (cool.loading || !cool.error ? <div className="skeleton" style={{ height: 320 }} /> : null) : (
        <>
          <div className="kpis">
            <Kpi hero label="Hottest wall" value={fmt(s.T_wall_max_K, 0)} unit="K" tone={s.wall_margin_K < 0 ? "bad" : s.wall_margin_K < 50 ? "warn" : "good"}
              sub={`${fmt(Math.abs(s.x_T_wall_max_m * 1e3), 1)} mm ${s.x_T_wall_max_m < 0 ? "before" : "after"} the throat`} />
            <Kpi label="Margin to limit" value={`${s.wall_margin_K >= 0 ? "+" : ""}${fmt(s.wall_margin_K, 0)}`} unit="K"
              tone={s.wall_margin_K < 0 ? "bad" : s.wall_margin_K < 50 ? "warn" : "good"} sub={`${s.wall_material} · ${fmt(s.T_wall_limit_K, 0)} K limit`} />
            {r.band && <Kpi label="Wall max band" value={`${fmt(r.band.lo.T_wall_max_K, 0)}–${fmt(r.band.hi.T_wall_max_K, 0)}`} unit="K" sub={`heat-transfer factor ±${r.band.tol}`} />}
            <Kpi label="Pressure drop" value={sig(s.dp_bar, 3)} unit="bar" sub={`outlet ${sig(s.outlet_p_bar, 3)} bar`} />
            <Kpi label="Coolant outlet" value={fmt(s.outlet_T_K, 0)} unit="K" tone="cool" sub={`from ${fmt(s.inlet_T_K, 0)} K`} />
            <Kpi label="Heat picked up" value={sig(s.Q_total_kW, 4)} unit="kW" />
            {s.feed_margin_bar != null && <Kpi label="Injector feed margin" value={`${s.feed_margin_bar >= 0 ? "+" : ""}${sig(s.feed_margin_bar, 3)}`} unit="bar"
              tone={s.feed_margin_bar < 0 ? "bad" : "good"} sub={`${sig(s.feed_required_p_bar, 3)} bar needed`} />}
            <Kpi label="Peak coolant Mach" value={fmt(s.coolant_mach_max, 2)} tone={s.coolant_mach_max > 0.3 ? "warn" : undefined} />
            {s.stress_ratio_max != null && <Kpi label="Stress / yield" value={fmt(s.stress_ratio_max, 2)} tone={s.stress_ratio_max > 1 ? "warn" : "good"} sub={`${fmt(s.sigma_max_MPa, 0)} MPa peak`} />}
          </div>
          {notes.length > 0 && <Callout tone="info"><b>Layout assistant:</b> {notes.join(" · ")}</Callout>}
          {s.wall_margin_K < 0 && <MarginHints />}
          <Tabs value={tab} onChange={setTab} options={[
            { value: "wall", label: "Wall temperature" }, { value: "coolant", label: "Coolant & p–h diagram" },
            { value: "geometry", label: "Channel geometry" }, { value: "structure", label: "Stress" }]} />
          {tab === "wall" && <WallTab />}
          {tab === "coolant" && <CoolantTab />}
          {tab === "geometry" && <GeometryTab />}
          {tab === "structure" && <StructureTab />}
          <Warnings items={r.warnings} />
          <p className="muted" style={{ fontSize: 12 }}>
            {s.stations} stations ({r.fidelity === "full" ? "full resolution" : `fast preview of ${s.full_stations}`}) · {s.n_channels} channels ·
            coolant model {s.correlation} · solved in {fmt(r.elapsed_s, 2)} s · energy balance {sig(s.energy_balance_kW, 2)} kW
          </p>
        </>
      )}
    </section>
  );
}

/** What usually brings an over-temperature wall back under its limit, ranked from the solution. */
function MarginHints() {
  const { cool, config } = useSession();
  const r = cool.data!;
  const s = r.summary, p = r.profiles;
  const v = Math.max(...(p.v_m_s as number[]).filter(Number.isFinite));
  const liquid = Math.max(...(p.rho as number[]).filter(Number.isFinite)) > 150;
  const copper = /cu|grcop|copper/i.test(String(s.wall_material));
  const hints: string[] = [];
  if (liquid ? v < 20 : s.coolant_mach_max < 0.1)
    hints.push(`Speed up the coolant (now ${sig(v, 2)} m/s): lower the channel height or use fewer channels around the throat.`);
  if (!copper) hints.push("Use a copper alloy (CuCrZr, GRCop-42): ~20× the conductivity of nickel alloys — the hot wall runs far cooler.");
  if (!config?.film_cooling) hints.push("Add a few percent film cooling (Heat load section) to protect the throat region.");
  hints.push("Thin the hot wall at the throat — use a profile that varies along the engine.");
  if (config?.chamber?.bartz_correction >= 1) hints.push("The heat-transfer factor is the textbook 1.0; small engines often measure 0.6–0.8. Calibrate it when test data is available.");
  hints.push("Lower chamber pressure reduces heat flux roughly as Pc^0.8.");
  return (
    <Callout tone="bad">
      <b>The hot wall is {fmt(-s.wall_margin_K, 0)} K above its limit.</b> Options, most effective first:
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{hints.slice(0, 4).map((h) => <li key={h}>{h}</li>)}</ul>
    </Callout>
  );
}

function twoPhase(x: number[], q: (number | null)[]): Shade[] {
  const out: Shade[] = [];
  let start: number | null = null;
  for (let i = 0; i < x.length; i++) {
    const tp = q[i] != null && (q[i] as number) >= 0 && (q[i] as number) <= 1;
    if (tp && start === null) start = x[i];
    if (!tp && start !== null) { out.push({ x0: start, x1: x[i - 1], color: "var(--s4)", label: out.length ? undefined : "boiling / two-phase" }); start = null; }
  }
  if (start !== null) out.push({ x0: start, x1: x[x.length - 1], color: "var(--s4)", label: out.length ? undefined : "boiling / two-phase" });
  return out;
}

function WallTab() {
  const r = useSession((s) => s.cool.data)!;
  const p = r.profiles;
  const x = (p.x_m as number[]).map((v) => v * 1e3);
  const series: Series[] = [
    { id: "hot", label: "Hot-gas side wall", color: "var(--s1)", x, y: p.T_wall_hot_K, unit: "K", digits: 4 },
    { id: "cold", label: "Coolant side wall", color: "var(--s3)", x, y: p.T_wall_cold_K, unit: "K", digits: 4 },
    { id: "cool", label: "Coolant bulk", color: "var(--s2)", x, y: p.T_cool_K, unit: "K", digits: 4 },
  ];
  if (r.skirt) series.push({ id: "skirt", label: "Radiation-cooled extension", color: "var(--s5)", dash: true, x: r.skirt.x_m.map((v) => v * 1e3), y: r.skirt.T_wall_K, unit: "K", digits: 4 });
  return (
    <>
      <ChartCard title="Wall temperature along the engine" sub="x = 0 at the throat · coolant flows right to left in counter-flow">
        <LineChart height={320} xLabel="Axial position [mm]" yLabel="Temperature [K]" series={series}
          silhouette={{ x, r: p.r_m as number[] }} xMarks={[{ x: 0, label: "throat" }]} shades={twoPhase(x, p.quality)}
          refLines={[{ y: r.wall_limit_K, label: `material limit ${fmt(r.wall_limit_K, 0)} K`, color: "var(--bad)" }]} />
      </ChartCard>
      <ChartCard title="Heat flux into the wall">
        <LineChart height={220} xLabel="Axial position [mm]" yLabel="Heat flux [MW/m²]" zeroY legend={false}
          series={[{ id: "q", label: "Heat flux", color: "var(--s1)", x, y: (p.q_w_W_m2 as number[]).map((v) => v / 1e6), unit: "MW/m²" }]} />
      </ChartCard>
    </>
  );
}

function CoolantTab() {
  const r = useSession((s) => s.cool.data)!;
  const p = r.profiles;
  const x = (p.x_m as number[]).map((v) => v * 1e3);
  const ph = r.ph;
  return (
    <>
      {ph && !ph.error ? (
        <ChartCard title={`Coolant path on the p–h diagram · ${ph.fluid}`} sub={`critical point ${sig(ph.p_crit_bar, 3)} bar / ${fmt(ph.T_crit_K, 0)} K`}>
          <PhChart height={360}
            dome={{ hl: ph.dome.h_liquid_kJ_kg, pl: ph.dome.p_liquid_bar, hv: ph.dome.h_vapor_kJ_kg, pv: ph.dome.p_vapor_bar }}
            isotherms={ph.isotherms.map((i) => ({ T: i.T_K, h: i.h_kJ_kg, p: i.p_bar }))}
            path={{ h: r.path.h_kJ_kg, p: r.path.p_bar, x: r.path.x_m, label: "coolant, inlet → outlet", color: "var(--s2)" }}
            crit={{ h: ph.h_crit_kJ_kg, p: ph.p_crit_bar }} />
          <p className="field-hint" style={{ marginTop: 6 }}>
            {r.summary.outlet_p_bar > ph.p_crit_bar ? "The coolant stays above its critical pressure — no boiling, but watch the property swing near the pseudo-critical temperature."
              : r.summary.saturation_reached ? "Part of the path lies inside the two-phase dome: the coolant boils there."
              : "Subcritical and single-phase along the whole path."}
          </p>
        </ChartCard>
      ) : <Callout tone="warn">p–h diagram unavailable: {ph?.error}</Callout>}
      <div className="split">
        <ChartCard title="Coolant temperature">
          <LineChart height={220} xLabel="Axial position [mm]" yLabel="Temperature [K]" series={[
            { id: "t", label: "Coolant bulk", color: "var(--s2)", x, y: p.T_cool_K, unit: "K", digits: 4 },
            { id: "sat", label: "Boiling point at local pressure", color: "var(--s4)", x, y: p.T_sat_K, unit: "K", dash: true, digits: 4 },
          ]} />
        </ChartCard>
        <ChartCard title="Coolant pressure">
          <LineChart height={220} xLabel="Axial position [mm]" yLabel="Pressure [bar]" legend={false}
            series={[{ id: "p", label: "Pressure", color: "var(--s2)", x, y: p.p_cool_bar, unit: "bar", digits: 4 }]} />
        </ChartCard>
      </div>
      <div className="split">
        <ChartCard title="Coolant velocity">
          <LineChart height={200} xLabel="Axial position [mm]" yLabel="Velocity [m/s]" legend={false}
            series={[{ id: "v", label: "Velocity", color: "var(--s2)", x, y: p.v_m_s, unit: "m/s" }]} />
        </ChartCard>
        <ChartCard title="Coolant heat-transfer coefficient">
          <LineChart height={200} xLabel="Axial position [mm]" yLabel="h [kW/m²K]" legend={false}
            series={[{ id: "hc", label: "Coolant side", color: "var(--s2)", x, y: (p.h_c as number[]).map((v) => v / 1e3), unit: "kW/m²K" }]} />
        </ChartCard>
      </div>
    </>
  );
}

function GeometryTab() {
  const { geo, loadGeometry, config, cool } = useSession();
  const [x, setX] = useState<number | null>(null);
  useEffect(() => { void loadGeometry(x); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const g = geo.data;
  const st = g?.section.station;
  const exportChannel = async (fmtName: "stl" | "step") => {
    if (!config) return;
    try { downloadBlob(await calc.exportChannel(config, fmtName), `${config.engine}_channel.${fmtName}`); }
    catch (e) { toast((e as Error).message, "bad"); }
  };
  const heat = cool.data?.ok ? { x_m: cool.data.profiles.x_m as number[], value: cool.data.profiles.T_wall_hot_K as number[] } : null;
  const prof = g?.section.profiles;
  const xp = prof ? prof.x_m.map((v) => v * 1e3) : [];
  return (
    <>
      <div className="split">
        <ChartCard title="Cross-section" sub={st ? `at x = ${fmt((g!.section.x_m) * 1e3, 1)} mm` : ""}>
          {g && st ? (
            <>
              <CrossSection r={st.r_m} t={st.wall_thickness_m} h={st.channel_height_m} w={st.channel_width_m} rib={st.rib_width_m}
                n={st.n_channels} closeout={g.assembly.closeout_thickness_m} />
              <input className="slider" type="range" min={g.section.x_range[0] * 1e3} max={g.section.x_range[1] * 1e3} step={0.5}
                value={(x ?? g.section.x_m) * 1e3} onChange={(e) => { const v = Number(e.target.value) / 1e3; setX(v); void loadGeometry(v); }} />
              <div className="row muted" style={{ fontSize: 11.5, justifyContent: "space-between" }}><span>injector end</span><span>throat</span><span>nozzle end</span></div>
            </>
          ) : <div className="skeleton" style={{ height: 230 }} />}
        </ChartCard>
        <ChartCard title="Manufacturing export" sub="one channel, true geometry">
          <div className="stack-sm">
            <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>Download a channel as a solid for CAD — pattern it {st?.n_channels ?? ""}× around the axis.</p>
            <div className="row">
              <button className="btn" onClick={() => exportChannel("stl")}><Icon name="download" size="sm" />STL</button>
              <button className="btn" onClick={() => exportChannel("step")}><Icon name="download" size="sm" />STEP</button>
            </div>
            {st && <dl className="kv" style={{ marginTop: 6 }}>
              <dt>Channel width</dt><dd>{sig(st.channel_width_m * 1e3, 3)}<span className="u">mm</span></dd>
              <dt>Channel height</dt><dd>{sig(st.channel_height_m * 1e3, 3)}<span className="u">mm</span></dd>
              <dt>Rib width</dt><dd>{sig(st.rib_width_m * 1e3, 3)}<span className="u">mm</span></dd>
              <dt>Hot-wall thickness</dt><dd>{sig(st.wall_thickness_m * 1e3, 3)}<span className="u">mm</span></dd>
              <dt>Spiral angle</dt><dd>{fmt(st.beta_deg, 1)}<span className="u">°</span></dd>
            </dl>}
          </div>
        </ChartCard>
      </div>
      {prof && <ChartCard title="Channel dimensions along the engine">
        <LineChart height={240} xLabel="Axial position [mm]" yLabel="Dimension [mm]" zeroY series={[
          { id: "w", label: "Channel width", color: "var(--s2)", x: xp, y: prof.channel_width_m.map((v) => v * 1e3), unit: "mm" },
          { id: "h", label: "Channel height", color: "var(--s3)", x: xp, y: prof.height_m.map((v) => v * 1e3), unit: "mm" },
          { id: "rib", label: "Rib width", color: "var(--s4)", x: xp, y: prof.rib_width_m.map((v) => v * 1e3), unit: "mm" },
          { id: "t", label: "Hot-wall thickness", color: "var(--s1)", x: xp, y: prof.wall_thickness_m.map((v) => v * 1e3), unit: "mm" },
        ]} xMarks={[{ x: 0, label: "throat" }]} />
      </ChartCard>}
      <ChartCard title="Wall assembly in 3D" sub="hot wall tinted by temperature · drag to orbit">
        {g ? <Suspense fallback={<div className="skeleton" style={{ height: 380 }} />}>
          <EngineViewer assembly={g.assembly} heat={heat} height={380} />
        </Suspense> : <div className="skeleton" style={{ height: 380 }} />}
      </ChartCard>
    </>
  );
}

function StructureTab() {
  const r = useSession((s) => s.cool.data)!;
  const p = r.profiles;
  const x = (p.x_m as number[]).map((v) => v * 1e3);
  if (r.summary.stress_ratio_max == null) return <Callout tone="info">Stress check is off, or the wall material has no strength data.</Callout>;
  return (
    <>
      <ChartCard title="Hot-wall stress relative to yield" sub="thermal + pressure bending, first-order (Huzel & Huang)">
        <LineChart height={260} xLabel="Axial position [mm]" yLabel="Stress / yield [–]" zeroY legend={false}
          series={[{ id: "sr", label: "Stress ratio", color: "var(--s1)", x, y: p.stress_ratio, digits: 3 }]}
          refLines={[{ y: 1, label: "yield", color: "var(--bad)" }]} />
      </ChartCard>
      <ChartCard title="Stress and strength">
        <LineChart height={240} xLabel="Axial position [mm]" yLabel="Stress [MPa]" zeroY series={[
          { id: "s", label: "Total stress", color: "var(--s1)", x, y: p.sigma_total_MPa, unit: "MPa" },
          { id: "y", label: "Yield strength at wall temperature", color: "var(--s3)", x, y: p.yield_MPa, unit: "MPa", dash: true },
        ]} />
      </ChartCard>
      <Callout tone="info">Thin regen walls usually yield at the throat on every firing; life is then set by low-cycle fatigue, not by this ratio alone.</Callout>
    </>
  );
}

