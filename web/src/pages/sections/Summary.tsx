import { ReactNode } from "react";
import { LineChart } from "../../components/charts/Chart";
import { EngineDrawing } from "../../components/charts/Drawing";
import { Warnings } from "../../components/ui/display";
import { Icon } from "../../components/ui/icons";
import { fmt, sig } from "../../lib/format";
import { useSession } from "../../lib/session";
import { useSettings } from "../../lib/stores";

function Row({ k, v, u }: { k: ReactNode; v: ReactNode; u?: string }) {
  return <><dt>{k}</dt><dd>{v}{u && <span className="u">{u}</span>}</dd></>;
}

export function SummarySection() {
  const { config, meta, projectName, perf, heat, cool, source } = useSession();
  const author = useSettings((s) => s.author);
  const p = perf.data?.performance, g = perf.data?.geometry, h = heat.data?.summary;
  const c = config?.regen && cool.data?.ok ? cool.data : null;
  const op = config?.operating_point, ap = config?.analyze_point;
  const pr = config?.propellants ?? {};
  const name = source?.kind === "scratch" ? "Quick estimate" : meta?.name;
  return (
    <section className="ws-results" style={{ maxWidth: 1100 }}>
      <div className="results-head no-print">
        <h3>Design sheet</h3><span className="spacer" />
        <button className="btn btn-primary" onClick={() => window.print()}><Icon name="report" size="sm" />Print / save as PDF</button>
      </div>
      {!p || !g ? <div className="skeleton" style={{ height: 400 }} /> : (
        <article className="report">
          <header style={{ display: "flex", gap: 20, alignItems: "flex-end", borderBottom: "2px solid var(--ink)", paddingBottom: 14 }}>
            <div style={{ flex: 1 }}>
              <div className="eyebrow">{projectName || "RESA Studio"} · engine design sheet</div>
              <h1>{name}</h1>
              <div className="muted">{pr.name} · {config?.engine}{meta?.head_version ? ` · version ${meta.head_version}${meta.has_unsaved_changes ? " + unsaved edits" : ""}` : ""}{meta ? ` · ${meta.status}` : ""}</div>
            </div>
            <div className="mono" style={{ fontSize: 12, textAlign: "right" }}>
              {new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}<br />{author || meta?.updated_by || ""}
            </div>
          </header>

          <div className="grid-2" style={{ gap: 28 }}>
            <section>
              <h2>Requirements & inputs</h2>
              <dl className="kv">
                <Row k="Propellants" v={`${pr.oxidizer} / ${pr.fuel}`} />
                <Row k="Delivery temperatures" v={`${fmt(pr.ox_temp_K, 0)} / ${fmt(pr.fuel_temp_K, 0)}`} u="K" />
                {op && <Row k="Thrust" v={sig(op.thrust_N, 4)} u="N" />}
                {op && <Row k="Chamber pressure" v={fmt(op.pc_bar, 2)} u="bar" />}
                {ap && <Row k="Measured flows ox / fuel" v={`${sig(ap.mdot_ox_kg_s, 4)} / ${sig(ap.mdot_fuel_kg_s, 4)}`} u="kg/s" />}
                <Row k="Mixture ratio O/F" v={op?.of_ratio == null && op ? `best Isp (${fmt(p.of_ratio, 2)})` : fmt(p.of_ratio, 2)} />
                <Row k="Ambient pressure" v={fmt(p.p_amb_bar, 3)} u="bar" />
                <Row k="Combustion / nozzle efficiency" v={`${fmt(p.eta_cstar, 3)} / ${fmt(p.eta_cf, 3)}`} />
                <Row k="Nozzle flow model" v={perf.data!.propellant_states.nozzle_flow.replace(/_/g, " ")} />
                <Row k="Contraction ratio / L*" v={`${fmt(g.contraction_ratio, 2)} / ${fmt(config?.chamber?.l_star_m, 2)} m`} />
              </dl>
            </section>
            <section>
              <h2>Performance</h2>
              <dl className="kv">
                <Row k={p.p_amb_bar === 0 ? "Isp (vacuum)" : "Isp at ambient"} v={fmt(p.isp_s, 1)} u="s" />
                {p.isp_vac_s != null && p.p_amb_bar !== 0 && <Row k="Isp (vacuum)" v={fmt(p.isp_vac_s, 1)} u="s" />}
                <Row k="Thrust" v={sig(p.thrust_N, 4)} u="N" />
                <Row k="Chamber pressure" v={fmt(p.pc_bar, 2)} u="bar" />
                <Row k="Total / ox / fuel flow" v={`${sig(p.mdot_total_kg_s, 4)} / ${sig(p.mdot_ox_kg_s, 4)} / ${sig(p.mdot_fuel_kg_s, 4)}`} u="kg/s" />
                <Row k="c* (effective)" v={fmt(p.cstar_m_s, 0)} u="m/s" />
                <Row k="Thrust coefficient" v={fmt(p.cf, 4)} />
                <Row k="Chamber temperature" v={fmt(p.tc_K, 0)} u="K" />
                <Row k="Exit pressure / Mach" v={`${sig(p.pe_bar, 3)} bar / ${fmt(p.exit_mach, 2)}`} />
              </dl>
            </section>
          </div>

          <section>
            <h2>Geometry</h2>
            <EngineDrawing x={perf.data!.contour.x_m} r={perf.data!.contour.r_m} height={250} animate={false}
              channelSpan={config?.regen && c ? [Math.min(...(c.profiles.x_m as number[])), Math.max(...(c.profiles.x_m as number[]))] : null}
              dims={{ chamber_d: g.chamber_diameter_m, throat_d: g.throat_diameter_m, exit_d: g.exit_diameter_m, chamber_len: g.chamber_length_m, nozzle_len: g.nozzle_length_m }} />
            <dl className="kv" style={{ gridTemplateColumns: "1fr auto 1fr auto", marginTop: 10 }}>
              <Row k="Throat Ø" v={sig(g.throat_diameter_m * 1e3, 4)} u="mm" />
              <Row k="Exit Ø / area ratio" v={`${sig(g.exit_diameter_m * 1e3, 4)} mm / ${fmt(g.eps, 1)}`} />
              <Row k="Chamber Ø" v={sig(g.chamber_diameter_m * 1e3, 4)} u="mm" />
              <Row k="Overall length" v={sig(g.total_length_m * 1e3, 4)} u="mm" />
            </dl>
          </section>

          {h && (
            <section>
              <h2>Heat load (wall at {fmt(heat.data!.wall_temp_K, 0)} K)</h2>
              <dl className="kv" style={{ gridTemplateColumns: "1fr auto 1fr auto" }}>
                <Row k="Peak heat flux" v={sig(h.q_max_W_m2 / 1e6, 3)} u="MW/m²" />
                <Row k="Total heat load" v={sig(h.Q_total_W / 1e3, 4)} u="kW" />
                <Row k="Chamber / nozzle" v={`${sig(h.Q_chamber_W / 1e3, 3)} / ${sig(h.Q_nozzle_W / 1e3, 3)}`} u="kW" />
                <Row k="Heat-transfer factor" v={`${h.bartz_correction}${h.bartz_correction_tol ? ` ± ${h.bartz_correction_tol}` : ""}`} />
              </dl>
            </section>
          )}

          {c && (
            <section>
              <h2>Cooling channels</h2>
              <dl className="kv" style={{ gridTemplateColumns: "1fr auto 1fr auto", marginBottom: 12 }}>
                <Row k="Coolant" v={`${c.summary.coolant} (${c.summary.coolant_side})`} />
                <Row k="Channels" v={c.summary.n_channels} />
                <Row k="Hottest wall" v={fmt(c.summary.T_wall_max_K, 0)} u="K" />
                <Row k="Margin to limit" v={`${fmt(c.summary.wall_margin_K, 0)} K (${c.summary.wall_material})`} />
                <Row k="Pressure drop" v={sig(c.summary.dp_bar, 3)} u="bar" />
                <Row k="Coolant in → out" v={`${fmt(c.summary.inlet_T_K, 0)} → ${fmt(c.summary.outlet_T_K, 0)}`} u="K" />
              </dl>
              <LineChart height={230} xLabel="Axial position [mm]" yLabel="Temperature [K]"
                series={[
                  { id: "hot", label: "Hot-gas side wall", color: "var(--s1)", x: (c.profiles.x_m as number[]).map((v) => v * 1e3), y: c.profiles.T_wall_hot_K, unit: "K" },
                  { id: "cool", label: "Coolant", color: "var(--s2)", x: (c.profiles.x_m as number[]).map((v) => v * 1e3), y: c.profiles.T_cool_K, unit: "K" },
                ]}
                refLines={[{ y: c.wall_limit_K, label: "limit", color: "var(--bad)" }]} />
            </section>
          )}

          <section>
            <h2>Notes & checks</h2>
            {(perf.data!.warnings.length || c?.warnings.length)
              ? <Warnings items={[...perf.data!.warnings, ...(c?.warnings ?? [])]} />
              : <p className="muted">No warnings from the sanity checks.</p>}
            {meta?.description && <p>{meta.description}</p>}
            <p className="muted" style={{ fontSize: 11.5 }}>Chemistry: {perf.data!.propellant_states.oxidizer}; {perf.data!.propellant_states.fuel}. Generated by RESA Studio.</p>
          </section>
        </article>
      )}
    </section>
  );
}
