/**
 * P2 studio features — sweep charts, regen KPIs, session helpers.
 */
(function () {
  function drawLineChart(canvas, xs, ys, { stroke = "#5b8def", label = "" } = {}) {
    const ctx = canvas.getContext("2d");
    if (!ctx || !xs?.length || !ys?.length) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 280;
    const h = parseInt(canvas.getAttribute("height"), 10) || 100;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "var(--bg, #0f1014)";
    ctx.fillRect(0, 0, w, h);

    const pad = { l: 36, r: 8, t: 10, b: 22 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const yMin = Math.min(...ys);
    const yMax = Math.max(...ys);
    const yPad = (yMax - yMin) * 0.08 || 1;
    const toX = (x) => pad.l + ((x - xMin) / (xMax - xMin || 1)) * plotW;
    const toY = (y) => pad.t + plotH - ((y - yMin + yPad) / (yMax - yMin + 2 * yPad || 1)) * plotH;

    ctx.strokeStyle = "rgba(140,148,160,0.25)";
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + plotH);
    ctx.lineTo(pad.l + plotW, pad.t + plotH);
    ctx.stroke();

    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < xs.length; i++) {
      const px = toX(xs[i]);
      const py = toY(ys[i]);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.stroke();

    ctx.fillStyle = "var(--text-muted, #8b949e)";
    ctx.font = "9px system-ui,sans-serif";
    ctx.fillText(label, pad.l, h - 6);
    ctx.textAlign = "right";
    ctx.fillText(yMax.toFixed(0), pad.l - 4, pad.t + 8);
    ctx.fillText(yMin.toFixed(0), pad.l - 4, pad.t + plotH);
    ctx.textAlign = "left";
  }

  function renderSweepBlock(title, canvasId, x, y, xLabel, yLabel) {
    const wrap = document.createElement("div");
    wrap.className = "sweep-chart-block";
    wrap.innerHTML = `<div class="sweep-chart-title">${title}</div>`;
    const canvas = document.createElement("canvas");
    canvas.className = "sweep-chart";
    canvas.id = canvasId;
    canvas.setAttribute("height", "100");
    wrap.appendChild(canvas);
    requestAnimationFrame(() => drawLineChart(canvas, x, y, { label: `${yLabel} vs ${xLabel}` }));
    return wrap;
  }

  function renderOffdesignPreviews(container, offdesign) {
    if (!container) return;
    container.innerHTML = "";
    if (!offdesign) {
      container.innerHTML = '<p class="form-hint">Enable off-design sweeps and run fast to see charts here.</p>';
      return;
    }

    const grid = document.createElement("div");
    grid.className = "sweep-charts-grid";

    if (offdesign.ox_throttle?.thrust_N) {
      const s = offdesign.ox_throttle;
      const x = s.ox_fraction || s.mdot_ox_kg_s;
      const xLabel = s.ox_fraction ? "ox fraction" : "mdot ox";
      grid.appendChild(renderSweepBlock("Ox throttle · thrust", "sweep-ox", x, s.thrust_N, xLabel, "N"));
    }
    if (offdesign.of_sweep?.isp_s) {
      const s = offdesign.of_sweep;
      grid.appendChild(renderSweepBlock("O/F sweep · Isp", "sweep-of", s.of, s.isp_s, "O/F", "s"));
    }
    if (offdesign.envelope?.thrust_N) {
      const s = offdesign.envelope;
      grid.appendChild(renderSweepBlock(
        "Envelope · thrust (1D slice)",
        "sweep-env",
        s.throttle_frac || s.of,
        s.thrust_N,
        s.throttle_frac ? "throttle" : "O/F",
        "N"
      ));
    }

    if (!grid.children.length) {
      container.innerHTML = '<p class="form-hint">No sweep data in last run.</p>';
      return;
    }
    container.appendChild(grid);
  }

  const REGEN_KPI_FIELDS = [
    ["Q_total_kW", "Q total", "kW"],
    ["T_wall_max_K", "T_wall max", "K"],
    ["dp_bar", "Δp cool", "bar"],
    ["outlet_T_K", "T_out", "K"],
  ];

  function appendRegenKpis(kpiContainer, regen) {
    if (!kpiContainer || !regen) return;
    for (const [key, label, unit] of REGEN_KPI_FIELDS) {
      if (regen[key] == null) continue;
      const val = typeof regen[key] === "number"
        ? (Number.isInteger(regen[key]) ? regen[key] : regen[key].toFixed(2))
        : regen[key];
      const card = document.createElement("div");
      card.className = "kpi kpi-regen";
      card.innerHTML = `
        <div class="kpi-label">${label}</div>
        <div class="kpi-value">${val} ${unit}</div>
        <div class="kpi-src">regen solver</div>
      `;
      kpiContainer.appendChild(card);
    }
  }

  function renderRunBadge(container, meta) {
    if (!container) return;
    const { mode, outdir, config_hash: hash } = meta || {};
    let text = mode === "full" ? "Full report" : "Fast run";
    if (outdir) text += ` · ${outdir}`;
    else if (hash) text += ` · ${hash}`;
    container.textContent = text;
    container.className = "results-source-badge " + (mode === "full" ? "is-full" : "is-fast");
    container.classList.remove("hidden");
  }

  const RECENT_KEY = "resa-studio-recent";
  const PINNED_KEY = "resa-studio-pinned";
  const MAX_RECENT = 8;

  function loadList(key) {
    try {
      return JSON.parse(localStorage.getItem(key) || "[]");
    } catch {
      return [];
    }
  }

  function saveList(key, list) {
    localStorage.setItem(key, JSON.stringify(list.slice(0, MAX_RECENT)));
  }

  function touchRecent(path) {
    if (!path) return;
    const list = loadList(RECENT_KEY).filter((p) => p !== path);
    list.unshift(path);
    saveList(RECENT_KEY, list);
  }

  function togglePin(path) {
    const pins = new Set(loadList(PINNED_KEY));
    if (pins.has(path)) pins.delete(path);
    else pins.add(path);
    saveList(PINNED_KEY, [...pins]);
    return pins.has(path);
  }

  function isPinned(path) {
    return loadList(PINNED_KEY).includes(path);
  }

  function renderDiffTable(rows) {
    if (!rows?.length) {
      return '<p class="form-hint">No differences found.</p>';
    }
    const head = "<tr><th>Key</th><th>A</th><th>B</th><th>Δ</th></tr>";
    const body = rows.map((r) =>
      `<tr><td>${r.key}</td><td>${r.a}</td><td>${r.b}</td><td>${r.delta || "—"}</td></tr>`
    ).join("");
    return `<table class="diff-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  }

  window.StudioP2 = {
    drawLineChart,
    renderOffdesignPreviews,
    appendRegenKpis,
    renderRunBadge,
    touchRecent,
    togglePin,
    isPinned,
    loadList,
    renderDiffTable,
    RECENT_KEY,
    PINNED_KEY,
  };
})();
