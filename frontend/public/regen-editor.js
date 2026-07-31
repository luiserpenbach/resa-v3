/**
 * Regen engine-sync matrix UI.
 */
(function () {
  const SYNC_FIELDS = [
    ["contour", "Contour geometry"],
    ["hot_gas_pc_bar", "Chamber pressure Pc"],
    ["hot_gas_tc_K", "Combustion temperature Tc"],
    ["hot_gas_gamma", "Ratio of specific heats γ"],
    ["hot_gas_mol_mass_kg_kmol", "Molecular mass"],
    ["hot_gas_c_star_m_s", "Characteristic velocity c*"],
    ["hot_gas_bartz_correction", "Bartz correction"],
    ["of_ratio", "O/F ratio"],
    ["mdot", "Coolant / engine mdot"],
  ];

  function buildSyncMatrix(editor, sync) {
    const grid = document.createElement("div");
    grid.className = "sync-matrix";
    for (const [key, label] of SYNC_FIELDS) {
      const lbl = document.createElement("label");
      lbl.className = "sync-toggle";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = sync?.[key] !== false;
      cb.addEventListener("change", () => {
        editor._setPath(["regen", "sync", key], cb.checked, { notify: true });
      });
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(` ${label}`));
      grid.appendChild(lbl);
    }
    return grid;
  }

  window.RegenEditor = {
    buildSyncMatrix,
  };
})();
