import { Suspense, lazy } from "react";
import { EngineDrawing } from "../../components/charts/Drawing";
import { Disclosure, Group, NumberField, SegField } from "../../components/ui/controls";
import { Warnings } from "../../components/ui/display";
import { Icon } from "../../components/ui/icons";
import { downloadText } from "../../lib/api";
import { fmt, sig } from "../../lib/format";
import { useSession } from "../../lib/session";
import { CalcError, InputProblems, Inputs, Progress, ResultsHead } from "./common";

export const EngineViewer = lazy(() => import("../../components/three/EngineViewer"));

export function ChamberSection() {
  return (
    <div className="ws-main">
      <ChamberInputs />
      <ChamberResults />
    </div>
  );
}

function ChamberInputs() {
  const contour = useSession((s) => s.config?.chamber?.contour);
  return (
    <Inputs title="Chamber & nozzle" lede="The shape follows from the throat size. Set how much chamber volume and what nozzle shape you want.">
      <Group title="Combustion chamber" no="1">
        <NumberField path={["chamber", "contraction_ratio"]} label="Contraction ratio" sym="Ac/At"
          hint="Chamber-to-throat area. 2–4 for large engines, 6–15 for small ones." />
        <NumberField path={["chamber", "l_star_m"]} label="Characteristic length" sym="L*" unit="m"
          hint="Chamber volume ÷ throat area — residence time for combustion. ~0.8–1.2 m (LOX/RP-1), 0.6–0.9 m (hydrogen)." />
        <NumberField path={["chamber", "conv_half_angle_deg"]} label="Convergent half-angle" unit="°" />
      </Group>
      <Group title="Nozzle" no="2">
        <SegField path={["chamber", "contour"]} label="Shape" options={[{ value: "rao_bell", label: "Bell (Rao)" }, { value: "conical", label: "Cone" }]} />
        {contour !== "conical" && <NumberField path={["chamber", "bell_fraction"]} label="Bell length" unit="% of 15° cone" scale={100} hint="80 % is the classic compromise." />}
        <Disclosure summary="Throat and bell details">
          <div className="grid-2">
            <NumberField path={["chamber", "rt_upstream_factor"]} label="Upstream throat radius" unit="× Rt" />
            <NumberField path={["chamber", "rt_downstream_factor"]} label="Downstream throat radius" unit="× Rt" />
          </div>
          <NumberField path={["chamber", "rc_entrance_factor"]} label="Chamber-to-convergent fillet" unit="× Dc" />
          {contour !== "conical" && <div className="grid-2">
            <NumberField path={["chamber", "theta_n_deg"]} label="Bell start angle" unit="°" nullable placeholder="auto" />
            <NumberField path={["chamber", "theta_e_deg"]} label="Bell exit angle" unit="°" nullable placeholder="auto" />
          </div>}
          <NumberField path={["chamber", "n_stations"]} label="Contour resolution" unit="points" integer />
        </Disclosure>
      </Group>
    </Inputs>
  );
}

function ChamberResults() {
  const { perf, config, errors } = useSession();
  const r = perf.data;
  const g = r?.geometry;
  const csv = () => {
    if (!r) return;
    const rows = r.contour.x_m.map((x, i) => `${(x * 1e3).toFixed(4)},${(r.contour.r_m[i] * 1e3).toFixed(4)}`);
    downloadText(`x_mm,r_mm\n${rows.join("\n")}\n`, `${config?.engine ?? "engine"}_contour.csv`, "text/csv");
  };
  return (
    <section className="ws-results">
      <Progress on={perf.loading} />
      <ResultsHead title="Geometry" loading={perf.loading} stale={perf.stale && errors.length > 0}>
        <button className="btn btn-sm" onClick={csv} disabled={!r}><Icon name="download" size="sm" />Contour CSV</button>
      </ResultsHead>
      <InputProblems />
      <CalcError error={perf.error} />
      {!r || !g ? <div className="skeleton" style={{ height: 300 }} /> : (
        <>
          <section className="card">
            <div className="card-body">
              <EngineDrawing x={r.contour.x_m} r={r.contour.r_m} height={330} dims={{
                chamber_d: g.chamber_diameter_m, throat_d: g.throat_diameter_m, exit_d: g.exit_diameter_m,
                chamber_len: g.chamber_length_m, nozzle_len: g.nozzle_length_m,
              }} />
            </div>
          </section>
          <div className="split">
            <section className="card">
              <div className="card-head"><h3>3D view</h3><span className="sub">drag to orbit</span></div>
              <div className="card-body">
                <Suspense fallback={<div className="skeleton" style={{ height: 320 }} />}>
                  <EngineViewer contour={r.contour} height={320} />
                </Suspense>
              </div>
            </section>
            <section className="card card-pad">
              <span className="eyebrow">Dimensions</span>
              <dl className="kv" style={{ marginTop: 10 }}>
                <dt>Chamber diameter</dt><dd>{sig(g.chamber_diameter_m * 1e3, 4)}<span className="u">mm</span></dd>
                <dt>Throat diameter</dt><dd>{sig(g.throat_diameter_m * 1e3, 4)}<span className="u">mm</span></dd>
                <dt>Exit diameter</dt><dd>{sig(g.exit_diameter_m * 1e3, 4)}<span className="u">mm</span></dd>
                <dt>Cylindrical length</dt><dd>{sig(g.cylinder_length_m * 1e3, 4)}<span className="u">mm</span></dd>
                <dt>Convergent length</dt><dd>{sig(g.convergent_length_m * 1e3, 4)}<span className="u">mm</span></dd>
                <dt>Injector to throat</dt><dd>{sig(g.chamber_length_m * 1e3, 4)}<span className="u">mm</span></dd>
                <dt>Nozzle length</dt><dd>{sig(g.nozzle_length_m * 1e3, 4)}<span className="u">mm</span></dd>
                <dt>Overall length</dt><dd>{sig(g.total_length_m * 1e3, 4)}<span className="u">mm</span></dd>
                <dt>Chamber volume</dt><dd>{sig(g.chamber_volume_m3 * 1e6, 4)}<span className="u">cm³</span></dd>
                <dt>Achieved L*</dt><dd>{fmt(g.l_star_m, 3)}<span className="u">m</span></dd>
                <dt>Bell start / exit angle</dt><dd>{fmt(g.theta_n_deg, 1)}° / {fmt(g.theta_e_deg, 1)}°</dd>
              </dl>
            </section>
          </div>
          <Warnings items={r.warnings} areas={["chamber"]} />
        </>
      )}
    </section>
  );
}
