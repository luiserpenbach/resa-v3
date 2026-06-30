"""One-off regen energy-balance diagnostic."""
from __future__ import annotations

from resa.config.loader import load_config
from resa.pipeline import run
from resa.regen.integration import contour_from_resa, prepare_regen_config
from resa.regen_channels.coolant import Coolant
from resa.regen_channels.layout import ChannelLayout
from resa.regen_channels.solver import RegenSolver


def main():
    cfg = load_config("configs/projects/e2_c1/design_regen.yaml")
    res = run(cfg)
    regen = prepare_regen_config(
        cfg.regen, res.thrust_chamber, res.combustion, cfg.chamber)
    lay = ChannelLayout(contour_from_resa(res.contour), regen)
    sol = RegenSolver(lay, regen)
    cool = Coolant(regen.solver.coolant)

    tc = res.thrust_chamber
    print("=== ENGINE ===")
    print(f"mdot_total engine: {tc.mdot_total_kg_s:.4f}")
    print(f"mdot_ox engine:    {tc.mdot_ox_kg_s:.4f}")
    print(f"At engine mm2:     {tc.throat_area_m2 * 1e6:.3f}")
    print(f"cstar ideal/eff:   {res.combustion.cstar_ideal_m_s:.1f} / {tc.cstar_eff_m_s:.1f}")

    print("\n=== SOLVER MDOT ===")
    print(f"hot.mdot (Bartz):  {sol.hot.mdot:.4f}")
    print(f"mdot_total solver: {sol.mdot_total:.4f}")
    print(f"mdot_ch:           {sol.mdot_ch:.6f}")
    print(f"N channels:        {lay.N}")

    df = sol.solve()
    a = df.attrs
    print("\n=== RESULTS ===")
    print(f"Q_total kW:        {a['Q_total_kW']:.1f}")
    print(f"inlet T K:         {regen.solver.inlet.temperature_K}")
    print(f"outlet T K:        {a['outlet_T_K']:.2f}")
    print(f"outlet p bar:      {a['outlet_p_bar']:.2f}")

    print("\n=== ENERGY BALANCE ===")
    print(f"h_in kJ/kg:        {a['inlet_h_kJ_kg']:.1f}")
    print(f"dh march kJ/kg:    {a['dh_kJ_kg']:.1f}")
    print(f"Q/mdot kJ/kg:      {a['Q_total_kW'] / sol.mdot_total:.1f}")
    print(f"closure kW:        {a['energy_balance_kW']:.2e}")

    cp_equiv = a["dh_kJ_kg"] / max(a["outlet_T_K"] - a["inlet_T_K"], 1e-6)
    print(f"equiv cp K avg:    {cp_equiv:.2f} kJ/kg/K (EOS, not constant)")

    Q_ch = df.Q_cell_W.sum()
    print(f"\nQ one channel W:   {Q_ch:.1f}")
    print(f"Q*N kW:            {Q_ch * lay.N / 1e3:.1f}")

    loc = a.get("coolant_inlet_location", "nozzle_end")
    path = (df.sort_values("x_m", ascending=False) if loc == "nozzle_end"
            else df.sort_values("x_m"))
    print(f"\nT at flow inlet K:  {path.T_cool_K.iloc[0]:.1f}")
    print(f"T at flow outlet K: {path.T_cool_out_K.iloc[-1]:.1f}")


if __name__ == "__main__":
    main()
