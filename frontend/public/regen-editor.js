/**
 * Structured regen profile editors — scalar or axial breakpoint tables.
 */
(function () {
  function isScalarProfile(val) {
    return typeof val === "number" || val == null;
  }

  function profileToRows(val) {
    if (isScalarProfile(val)) {
      const v = val ?? 0;
      return [["-0.30", String(v)], ["0.30", String(v)]];
    }
    if (Array.isArray(val)) {
      return val.map((p) => [String(p[0]), String(p[1])]);
    }
    return [["-0.30", "0"], ["0.30", "0"]];
  }

  function rowsToProfile(rows, asScalar) {
    const pts = rows
      .map((r) => [parseFloat(r[0]), parseFloat(r[1])])
      .filter((p) => !Number.isNaN(p[0]) && !Number.isNaN(p[1]));
    if (!pts.length) return 0;
    if (asScalar) return pts[0][1];
    pts.sort((a, b) => a[0] - b[0]);
    return pts;
  }

  function formatMm(v) {
    if (v == null || Number.isNaN(v)) return "—";
    return `${(v * 1000).toFixed(2)} mm`;
  }

  /**
   * @param {object} editor ConfigEditor instance
   * @param {object} opts
   * @param {string} opts.label
   * @param {string[]} opts.path
   * @param {boolean} [opts.allowBreakpoints=true]
   */
  function buildProfileField(editor, { label, path, allowBreakpoints = true }) {
    const wrap = document.createElement("div");
    wrap.className = "regen-profile-field form-field form-field-wide";
    wrap.dataset.configPath = path.join(".");

    const head = document.createElement("div");
    head.className = "regen-profile-head";
    head.innerHTML = `<label>${label}</label>`;
    wrap.appendChild(head);

    const val = editor._getPath(path);
    let breakpointMode = allowBreakpoints && !isScalarProfile(val);

    const modeRow = document.createElement("div");
    modeRow.className = "regen-profile-mode";
    if (allowBreakpoints) {
      const modeLbl = document.createElement("label");
      modeLbl.className = "toggle-inline";
      const modeCb = document.createElement("input");
      modeCb.type = "checkbox";
      modeCb.checked = breakpointMode;
      modeLbl.appendChild(modeCb);
      modeLbl.appendChild(document.createTextNode(" Axial breakpoints"));
      modeRow.appendChild(modeLbl);
      modeCb.addEventListener("change", () => {
        breakpointMode = modeCb.checked;
        renderBody();
        if (!breakpointMode) {
          const rows = profileToRows(editor._getPath(path));
          const v = parseFloat(rows[0][1]);
          editor._setPath(path, Number.isNaN(v) ? 0 : v, { notify: true });
        } else {
          const cur = editor._getPath(path);
          const scalar = typeof cur === "number" ? cur : parseFloat(profileToRows(cur)[0][1]) || 0;
          editor._setPath(path, [[-0.3, scalar], [0.3, scalar]], { notify: true });
        }
      });
    }
    wrap.appendChild(modeRow);

    const body = document.createElement("div");
    body.className = "regen-profile-body";
    wrap.appendChild(body);

    const renderBody = () => {
      body.innerHTML = "";
      const current = editor._getPath(path);
      if (!breakpointMode) {
        const scalarRow = document.createElement("div");
        scalarRow.className = "regen-scalar-row";
        const inp = document.createElement("input");
        inp.type = "number";
        inp.step = "any";
        inp.value = isScalarProfile(current) ? (current ?? "") : (profileToRows(current)[0][1] ?? "");
        inp.dataset.configPath = path.join(".");
        const hint = document.createElement("span");
        hint.className = "field-unit-hint";
        const syncHint = () => {
          const v = parseFloat(inp.value);
          hint.textContent = !Number.isNaN(v) ? formatMm(v) : "";
        };
        syncHint();
        inp.addEventListener("input", () => {
          const v = parseFloat(inp.value);
          if (Number.isNaN(v)) return;
          editor._setPath(path, v);
        });
        inp.addEventListener("change", () => {
          syncHint();
          editor._notifyChange(true);
        });
        scalarRow.appendChild(inp);
        scalarRow.appendChild(hint);
        body.appendChild(scalarRow);
        return;
      }

      const table = document.createElement("table");
      table.className = "regen-profile-table";
      table.innerHTML = `
        <thead><tr><th>x (m)</th><th>value (m)</th><th></th></tr></thead>
        <tbody></tbody>
      `;
      const tbody = table.querySelector("tbody");
      const rows = profileToRows(current);

      const commit = () => {
        const data = [];
        tbody.querySelectorAll("tr").forEach((tr) => {
          const xInp = tr.querySelector(".bp-x");
          const vInp = tr.querySelector(".bp-v");
          if (xInp && vInp) data.push([xInp.value, vInp.value]);
        });
        editor._setPath(path, rowsToProfile(data, false), { notify: true });
      };

      const addRow = (x = "0", v = "0.003") => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><input type="number" class="bp-x" step="any" value="${x}"></td>
          <td><input type="number" class="bp-v" step="any" value="${v}"></td>
          <td><button type="button" class="btn-icon bp-del" title="Remove">×</button></td>
        `;
        tr.querySelectorAll("input").forEach((inp) => {
          inp.addEventListener("input", commit);
          inp.addEventListener("change", () => editor._notifyChange(true));
        });
        tr.querySelector(".bp-del").addEventListener("click", () => {
          tr.remove();
          commit();
          editor._notifyChange(true);
        });
        tbody.appendChild(tr);
      };

      rows.forEach(([x, v]) => addRow(x, v));
      body.appendChild(table);

      const addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "btn-inline regen-add-bp";
      addBtn.textContent = "+ Add breakpoint";
      addBtn.addEventListener("click", () => {
        addRow("0", "0.003");
        commit();
      });
      body.appendChild(addBtn);
    };

    renderBody();
    return wrap;
  }

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
    buildProfileField,
    buildSyncMatrix,
    isScalarProfile,
  };
})();
