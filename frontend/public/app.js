const DEFAULT_CONFIG = "configs/projects/ex15/design.yaml";
const EXPANDED_PROJECTS_KEY = "resa-studio-expanded-projects";
const THEME_KEY = "resa-studio-theme";

const KPI_FIELDS = [
  ["thrust_N", "Thrust", "N", "thrust_src"],
  ["isp_s", "Isp", "s", null],
  ["pc_bar", "Pc", "bar", "pc_src"],
  ["of_ratio", "O/F", "", "of_src"],
  ["eps", "ε", "", "eps_src"],
  ["mdot_kg_s", "mdot", "kg/s", null],
  ["throat_r_mm", "Throat r", "mm", null],
];

const PLOT_ORDER = [
  "contour.html",
  "mach.html",
  "offdesign_ox_throttle.html",
  "offdesign_of_sweep.html",
  "offdesign_envelope.html",
];

const PLOT_LABELS = {
  "contour.html": "Contour",
  "mach.html": "Mach",
  "offdesign_ox_throttle.html": "Ox throttle",
  "offdesign_of_sweep.html": "O/F sweep",
  "offdesign_envelope.html": "Envelope",
};

const state = {
  activeRun: null,
  activeConfig: null,
  plotArtifacts: [],
  activePlot: null,
  editor: null,
  configs: [],
  projects: [],
  createConfigProject: null,
  configLoading: false,
  editSession: null,
  loadSeq: 0,
  lastRunData: null,
  savedRuns: [],
  compareA: null,
  compareB: null,
  plotSource: null,
};

const els = {
  configPath: document.getElementById("config-path"),
  configNav: document.getElementById("config-nav"),
  activeConfigPath: document.getElementById("active-config-path"),
  configEditor: document.getElementById("config-editor"),
  editorCard: document.getElementById("editor-card"),
  editModeBadge: document.getElementById("edit-mode-badge"),
  editHint: document.getElementById("edit-hint"),
  btnEdit: document.getElementById("btn-edit"),
  btnSave: document.getElementById("btn-save"),
  btnCancel: document.getElementById("btn-cancel"),
  btnTheme: document.getElementById("btn-theme"),
  autoRun: document.getElementById("auto-run"),
  health: document.getElementById("health"),
  status: document.getElementById("status"),
  warnings: document.getElementById("warnings"),
  resultsEmpty: document.getElementById("results-empty"),
  resultsSourceBadge: document.getElementById("results-source-badge"),
  offdesignSweeps: document.getElementById("offdesign-sweeps"),
  compareResults: document.getElementById("compare-results"),
  compareResultsBody: document.getElementById("compare-results-body"),
  kpis: document.getElementById("kpis"),
  provenanceBody: document.querySelector("#provenance-table tbody"),
  plotFrame: document.getElementById("plot-frame"),
  plotPlaceholder: document.getElementById("plot-placeholder"),
  plotTabs: document.getElementById("plot-tabs"),
  plotSourceBadge: document.getElementById("plot-source-badge"),
  runsList: document.getElementById("runs-list"),
  pinnedNav: document.getElementById("pinned-nav"),
  recentNav: document.getElementById("recent-nav"),
  campaignsList: document.getElementById("campaigns-list"),
  compareRunA: document.getElementById("compare-run-a"),
  compareRunB: document.getElementById("compare-run-b"),
  btnCompareRuns: document.getElementById("btn-compare-runs"),
  btnRefreshCampaigns: document.getElementById("btn-refresh-campaigns"),
  btnNewProject: document.getElementById("btn-new-project"),
  dialogNewProject: document.getElementById("dialog-new-project"),
  formNewProject: document.getElementById("form-new-project"),
  dialogNewConfig: document.getElementById("dialog-new-config"),
  formNewConfig: document.getElementById("form-new-config"),
  newConfigProjectLabel: document.getElementById("new-config-project-label"),
  artifactsList: document.getElementById("artifacts-list"),
  btnValidate: document.getElementById("btn-validate"),
  btnRunFast: document.getElementById("btn-run-fast"),
  btnRunFull: document.getElementById("btn-run-full"),
  btnRefreshRuns: document.getElementById("btn-refresh-runs"),
};

function getTheme() {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_KEY, theme);
  if (els.btnTheme) {
    const next = theme === "dark" ? "light" : "dark";
    els.btnTheme.textContent = next === "light" ? "Light" : "Dark";
    els.btnTheme.setAttribute("aria-label", `Switch to ${next} mode`);
  }
}

function toggleTheme() {
  applyTheme(getTheme() === "dark" ? "light" : "dark");
}

function setStatus(text, isError = false) {
  if (!text) {
    els.status.classList.add("hidden");
    return;
  }
  els.status.classList.remove("hidden");
  els.status.textContent = text;
  els.status.style.color = isError ? "var(--danger)" : "var(--text-muted)";
}

function setBusy(busy) {
  for (const btn of [els.btnValidate, els.btnRunFast, els.btnRunFull]) {
    btn.disabled = busy;
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(formatApiError(data, res.statusText));
  return data;
}

function parseValidationErrors(data) {
  if (Array.isArray(data.detail)) {
    return data.detail.map((e) => ({
      loc: e.loc || [],
      msg: e.msg || "",
      type: e.type || "",
    }));
  }
  return [];
}

async function validateConfigApi(config) {
  const res = await fetch("/api/config/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  const data = await res.json().catch(() => ({}));
  if (res.ok) return { ok: true, data };
  return {
    ok: false,
    errors: parseValidationErrors(data),
    message: formatApiError(data, res.statusText),
  };
}

function formatApiError(data, fallback) {
  const detail = data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((e) => `${(e.loc || []).join(".")}: ${e.msg}`).join("; ");
  }
  if (detail) return JSON.stringify(detail, null, 2);
  return fallback || "Request failed";
}

function artifactUrl(engine, configHash, filepath) {
  return `/api/artifacts/${engine}/${configHash}/${filepath}`;
}

function isPlotArtifact(name) {
  return name.endsWith(".html");
}

function plotLabel(name) {
  if (PLOT_LABELS[name]) return PLOT_LABELS[name];
  if (name.endsWith("_3d.html")) return name.replace("_3d.html", "").replace(/_/g, " ");
  return name.replace(".html", "").replace(/_/g, " ");
}

function sortPlots(artifacts) {
  const plots = artifacts.filter(isPlotArtifact);
  const ordered = [];
  for (const name of PLOT_ORDER) {
    if (plots.includes(name)) ordered.push(name);
  }
  for (const name of plots.sort()) {
    if (!ordered.includes(name)) ordered.push(name);
  }
  return ordered;
}

function formatRunTime(ts) {
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function projectSlugFromPath(path) {
  const m = path.match(/^configs\/projects\/([^/]+)\//);
  return m ? m[1] : null;
}

function configLabel(path) {
  const parts = path.replace(/^configs\//, "").split("/");
  return parts[parts.length - 1];
}

function selectConfig(path) {
  if (!confirmLeaveIfDirty()) return;
  state.loadSeq += 1;
  state.activeConfig = path;
  state.activeRun = null;
  state.editSession = null;
  state.configLoading = true;
  state.editor?.setEditable(false);
  updateEditUI();
  if (window.StudioP2) StudioP2.touchRecent(path);
  highlightActiveRun();
  els.configPath.value = path;
  if (els.activeConfigPath) els.activeConfigPath.textContent = path;
  highlightConfigNav();
  renderSessionNavs();
  loadEditorConfig();
}

function applyEditorPayload(data, { isRun = false } = {}) {
  const payload = {
    config_path: data.config_path || data.config_source,
    config: data.config,
    engine: data.engine,
    mode: data.mode || data.analysis_mode || "design",
    config_hash: data.config_hash,
    writable: data.writable !== false,
    save_path: data.save_path || data.config_path || data.config_source,
    is_override: !!data.is_override,
  };
  state.editSession = {
    baseline: null,
    dirty: false,
    editing: false,
    sourcePath: payload.config_path,
    savePath: payload.save_path,
    writable: payload.writable,
    isOverride: payload.is_override,
    isRun,
  };
  state.editor.loadConfig(payload);
  state.editSession.baseline = state.editor.getSnapshot();
  updateEditUI();
  if (!isRun) clearResults();
}

function updateEditUI() {
  const sess = state.editSession;
  const hasConfig = !!state.editor?.config;

  if (els.btnEdit) {
    els.btnEdit.disabled = !hasConfig || !sess?.writable || sess?.editing || state.configLoading;
    els.btnEdit.classList.toggle("hidden", sess?.editing);
  }
  if (els.btnSave) {
    els.btnSave.classList.toggle("hidden", !sess?.editing);
    els.btnSave.disabled = !sess?.dirty;
    els.btnSave.title = sess?.dirty
      ? (state.editor?.validationState.ok === false
        ? "Config has validation warnings — save will re-check"
        : "Save changes")
      : "No unsaved changes";
  }
  if (els.btnCancel) {
    els.btnCancel.classList.toggle("hidden", !sess?.editing);
  }
  if (els.editorCard) {
    els.editorCard.classList.toggle("is-editing", !!sess?.editing);
  }
  if (els.editModeBadge) {
    if (!hasConfig) {
      els.editModeBadge.textContent = "—";
      els.editModeBadge.className = "edit-mode-badge";
    } else if (!sess?.writable) {
      els.editModeBadge.textContent = "View only";
      els.editModeBadge.className = "edit-mode-badge";
    } else if (sess?.editing && sess.dirty) {
      els.editModeBadge.textContent = "Unsaved changes";
      els.editModeBadge.className = "edit-mode-badge is-dirty";
    } else if (sess?.editing) {
      els.editModeBadge.textContent = "Editing";
      els.editModeBadge.className = "edit-mode-badge is-editing";
    } else {
      els.editModeBadge.textContent = "Viewing";
      els.editModeBadge.className = "edit-mode-badge";
    }
  }
  if (els.editHint) {
    if (sess?.editing && sess.isRun) {
      els.editHint.textContent = "Save updates the run snapshot (config_resolved.yaml).";
      els.editHint.classList.remove("hidden");
    } else if (sess?.editing) {
      els.editHint.textContent = `Changes will be saved to ${sess.savePath}.`;
      els.editHint.classList.remove("hidden");
    } else {
      els.editHint.classList.add("hidden");
    }
  }
}

function confirmLeaveIfDirty() {
  const sess = state.editSession;
  if (!sess?.editing || !sess.dirty) return true;
  return window.confirm("Discard unsaved changes?");
}

async function enterEditMode() {
  const sess = state.editSession;
  if (!sess?.writable || !state.editor?.config) return;
  sess.editing = true;
  sess.dirty = false;
  state.editor.setEditable(true);
  updateEditUI();
  await validateEditorConfig(state.editor.getConfig(), { silent: true });
  updateEditUI();
  setStatus("Editing — save or cancel when done.");
}

function cancelEdit() {
  const sess = state.editSession;
  if (!sess?.baseline) return;
  state.editor.revertTo(sess.baseline);
  state.editor._clearDraft();
  sess.editing = false;
  sess.dirty = false;
  updateEditUI();
  validateEditorConfig(state.editor.getConfig(), { silent: true });
  clearResults();
  setStatus("Changes reverted.");
}

async function saveEdit() {
  const sess = state.editSession;
  if (!sess?.editing || !state.editor || !sess.dirty) return;
  const savePath = state.editor.meta?.config_path || sess.sourcePath;
  if (!savePath || savePath !== state.activeConfig) {
    setStatus(
      `Cannot save — editor path (${savePath || "?"}) does not match the selected config (${state.activeConfig || "?"}). Reselect it and try again.`,
      true
    );
    return;
  }
  const changes = state.editor.getChangeSummary();
  if (changes.length) {
    const preview = changes.slice(0, 12).map((c) => `• ${c}`).join("\n");
    const more = changes.length > 12 ? `\n• …and ${changes.length - 12} more` : "";
    const ok = window.confirm(
      `Save ${changes.length} changed field(s) to ${savePath}?\n\n${preview}${more}`
    );
    if (!ok) return;
  }
  setBusy(true);
  try {
    const config = state.editor.getConfig();
    const valid = await validateEditorConfig(config, { silent: true });
    if (!valid) {
      setStatus("Cannot save — fix validation errors highlighted in the form.", true);
      updateEditUI();
      return;
    }
    const res = await api("/api/config/save", {
      method: "POST",
      body: JSON.stringify({ config_path: savePath, config }),
    });
    sess.editing = false;
    sess.dirty = false;
    state.editor.clearEditSession();
    state.editor.setEditable(false);
    const msg = `Saved ${res.config_path}`;
    setStatus(msg);
    if (res.config_path.startsWith("configs/")) {
      await loadProjects();
      state.activeConfig = res.config_path;
      highlightConfigNav();
    }
    const resolved = await api(`/api/config/resolve?config_path=${encodeURIComponent(res.config_path)}`);
    applyEditorPayload(resolved);
    if (els.activeConfigPath) els.activeConfigPath.textContent = res.config_path;
    await validateEditorConfig(state.editor.getConfig(), { silent: true });
    clearResults();
  } catch (err) {
    setStatus(String(err.message), true);
  } finally {
    setBusy(false);
    updateEditUI();
  }
}

function markDirty(dirty) {
  if (state.editSession) state.editSession.dirty = dirty;
  updateEditUI();
}

function highlightConfigNav() {
  for (const btn of els.configNav.querySelectorAll(".nav-item[data-config]")) {
    const active = btn.dataset.config === state.activeConfig;
    btn.classList.toggle("active", !!active);
    if (active) {
      const block = btn.closest(".nav-project");
      if (block) block.open = true;
    }
  }
}

function highlightActiveRun() {
  for (const btn of els.runsList.querySelectorAll(".nav-item-run")) {
    const active =
      state.activeRun &&
      btn.dataset.engine === state.activeRun.engine &&
      btn.dataset.hash === state.activeRun.config_hash;
    btn.classList.toggle("active", !!active);
  }
}

function clearResults(message = "Run fast or a full report to see results.") {
  if (els.resultsEmpty) {
    els.resultsEmpty.textContent = message;
    els.resultsEmpty.classList.remove("hidden");
  }
  els.kpis.innerHTML = "";
  if (els.resultsSourceBadge) {
    els.resultsSourceBadge.textContent = "";
    els.resultsSourceBadge.classList.add("hidden");
  }
  if (els.offdesignSweeps) {
    els.offdesignSweeps.innerHTML = "";
    els.offdesignSweeps.classList.add("hidden");
  }
  if (els.compareResults) {
    els.compareResults.classList.add("hidden");
    if (els.compareResultsBody) els.compareResultsBody.innerHTML = "";
  }
  els.provenanceBody.innerHTML = "";
  els.warnings.classList.add("hidden");
  els.warnings.innerHTML = "";
  state.activeRun = null;
  state.lastRunData = null;
  state.plotSource = null;
  highlightActiveRun();
  state.activePlot = null;
  els.plotTabs.classList.add("hidden");
  els.plotTabs.innerHTML = "";
  els.plotFrame.classList.add("hidden");
  els.plotFrame.src = "";
  els.plotPlaceholder.classList.remove("hidden");
  els.plotPlaceholder.textContent = "Run a full report or open a saved run to view plots.";
  if (els.plotSourceBadge) {
    els.plotSourceBadge.textContent = "";
    els.plotSourceBadge.classList.add("hidden");
  }
  els.artifactsList.innerHTML = '<p class="placeholder">No artifacts yet.</p>';
}

function extractRunExtras(data) {
  const nested = data.result || data.results || {};
  return {
    regen: data.regen || nested.regen || null,
    offdesign: data.offdesign || nested.offdesign || null,
  };
}

function setPlotSourceBadge(kind) {
  if (!els.plotSourceBadge) return;
  if (!kind) {
    els.plotSourceBadge.classList.add("hidden");
    return;
  }
  els.plotSourceBadge.textContent = kind === "saved" ? "Saved run" : "Live run";
  els.plotSourceBadge.className = `plot-source-badge is-${kind}`;
  els.plotSourceBadge.classList.remove("hidden");
}

function renderSummary(summary, provenance) {
  if (els.resultsEmpty) els.resultsEmpty.classList.add("hidden");
  els.kpis.innerHTML = "";
  for (const [key, label, unit, srcKey] of KPI_FIELDS) {
    if (summary[key] === undefined || summary[key] === null) continue;
    const card = document.createElement("div");
    card.className = "kpi";
    const value = summary[key];
    const unitStr = unit ? ` ${unit}` : "";
    const src = srcKey && summary[srcKey] ? summary[srcKey] : provenance[key.replace("_src", "")] || "";
    card.innerHTML = `
      <div class="kpi-label">${label}</div>
      <div class="kpi-value">${value}${unitStr}</div>
      ${src ? `<div class="kpi-src">${src}</div>` : ""}
    `;
    els.kpis.appendChild(card);
  }

  els.provenanceBody.innerHTML = "";
  for (const [qty, src] of Object.entries(provenance || {})) {
    const row = document.createElement("tr");
    row.innerHTML = `<td>${qty}</td><td>${src}</td>`;
    els.provenanceBody.appendChild(row);
  }
}

function renderWarnings(warnings) {
  if (!warnings || warnings.length === 0) {
    els.warnings.classList.add("hidden");
    els.warnings.innerHTML = "";
    return;
  }
  els.warnings.classList.remove("hidden");
  els.warnings.innerHTML = `
    <strong>Warnings (${warnings.length})</strong>
    <ul>${warnings.map((w) => `<li>${w}</li>`).join("")}</ul>
  `;
}

function showPlot(engine, configHash, filename) {
  state.activePlot = filename;
  els.plotFrame.src = artifactUrl(engine, configHash, filename);
  els.plotFrame.classList.remove("hidden");
  els.plotPlaceholder.classList.add("hidden");
  setPlotSourceBadge(state.plotSource || "saved");
  for (const tab of els.plotTabs.querySelectorAll(".plot-tab")) {
    tab.classList.toggle("active", tab.dataset.file === filename);
    const isRegen = /regen/i.test(tab.dataset.file || "");
    const isOffdesign = (tab.dataset.file || "").startsWith("offdesign");
    tab.classList.toggle("plot-tab-regen", isRegen);
    tab.classList.toggle("plot-tab-offdesign", isOffdesign);
  }
}

function renderPlots(engine, configHash, artifacts) {
  const plots = sortPlots(artifacts);
  state.plotArtifacts = plots;

  if (plots.length === 0) {
    els.plotTabs.classList.add("hidden");
    els.plotTabs.innerHTML = "";
    els.plotFrame.classList.add("hidden");
    els.plotFrame.src = "";
    els.plotPlaceholder.classList.remove("hidden");
    els.plotPlaceholder.textContent = "No plots in this run. Run a full report to generate them.";
    setPlotSourceBadge(null);
    return;
  }

  els.plotTabs.classList.remove("hidden");
  els.plotTabs.innerHTML = plots
    .map((file) => {
      const cls = [];
      if (/regen/i.test(file)) cls.push("plot-tab-regen");
      if (file.startsWith("offdesign")) cls.push("plot-tab-offdesign");
      return `<button type="button" class="plot-tab ${cls.join(" ")}" data-file="${file}">${plotLabel(file)}</button>`;
    })
    .join("");

  for (const tab of els.plotTabs.querySelectorAll(".plot-tab")) {
    tab.addEventListener("click", () => showPlot(engine, configHash, tab.dataset.file));
  }

  setPlotSourceBadge(state.plotSource || "saved");
  showPlot(engine, configHash, plots.includes(state.activePlot) ? state.activePlot : plots[0]);
}

function renderArtifacts(engine, configHash, artifacts) {
  if (!artifacts || artifacts.length === 0) {
    els.artifactsList.innerHTML = '<p class="placeholder">No artifacts yet.</p>';
    return;
  }

  els.artifactsList.innerHTML = "";
  const sorted = [...artifacts].sort((a, b) => {
    const aPlot = isPlotArtifact(a);
    const bPlot = isPlotArtifact(b);
    if (aPlot !== bPlot) return aPlot ? -1 : 1;
    return a.localeCompare(b);
  });

  for (const file of sorted) {
    const link = document.createElement("a");
    link.href = artifactUrl(engine, configHash, file);
    const isPdf = file.endsWith(".pdf");
    link.className = `artifact-link${isPlotArtifact(file) ? " plot" : " download"}${isPdf ? " pdf" : ""}`;
    link.textContent = isPdf ? `📄 ${file}` : file;
    if (isPlotArtifact(file)) {
      link.addEventListener("click", (e) => {
        e.preventDefault();
        showPlot(engine, configHash, file);
      });
    } else {
      link.target = "_blank";
      link.rel = "noopener";
    }
    els.artifactsList.appendChild(link);
  }
}

function renderRun(data) {
  state.lastRunData = data;
  renderSummary(data.summary, data.provenance);
  renderWarnings(data.warnings);

  const extras = extractRunExtras(data);
  if (window.StudioP2) {
    StudioP2.appendRegenKpis(els.kpis, extras.regen);
    StudioP2.renderRunBadge(els.resultsSourceBadge, {
      mode: data.mode,
      outdir: data.outdir,
      config_hash: data.config_hash,
    });
    if (els.offdesignSweeps) {
      els.offdesignSweeps.classList.remove("hidden");
      StudioP2.renderOffdesignPreviews(els.offdesignSweeps, extras.offdesign);
    }
  }

  if (data.engine && data.config_hash && data.artifacts) {
    state.activeRun = { engine: data.engine, config_hash: data.config_hash };
    state.plotSource = "saved";
    renderPlots(data.engine, data.config_hash, data.artifacts);
    renderArtifacts(data.engine, data.config_hash, data.artifacts);
    highlightActiveRun();
    syncCompareSelects();
  } else if (data.mode === "fast") {
    state.activePlot = null;
    state.plotSource = "live";
    els.plotTabs.classList.add("hidden");
    els.plotFrame.classList.add("hidden");
    els.plotPlaceholder.classList.remove("hidden");
    els.plotPlaceholder.textContent = "Fast runs produce no artifacts. Run a full report for plots.";
    setPlotSourceBadge("live");
    els.artifactsList.innerHTML = '<p class="placeholder">No artifacts (fast run).</p>';
  }
}

async function loadRuns() {
  els.runsList.innerHTML = '<p class="placeholder">Loading…</p>';
  try {
    const runs = await api("/api/runs");
    state.savedRuns = runs;
    if (runs.length === 0) {
      els.runsList.innerHTML = '<p class="placeholder">No saved runs yet.</p>';
      syncCompareSelects();
      return;
    }

    els.runsList.innerHTML = "";
    for (const run of runs) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "nav-item nav-item-run";
      btn.dataset.engine = run.engine;
      btn.dataset.hash = run.config_hash;
      const kpis =
        run.thrust_N != null && run.isp_s != null
          ? `${run.thrust_N.toFixed(0)} N · ${run.isp_s.toFixed(1)} s`
          : "";
      const key = `${run.engine}|${run.config_hash}`;
      const pick =
        state.compareA === key ? " [A]" : state.compareB === key ? " [B]" : "";
      btn.innerHTML = `
        <div class="run-title">${run.engine}${pick}</div>
        <div class="run-meta">${kpis}${kpis ? " · " : ""}${formatRunTime(run.modified_at)}</div>
      `;
      btn.addEventListener("click", (e) => {
        if (e.shiftKey) {
          pickCompareRun(run.engine, run.config_hash);
          return;
        }
        openRun(run.engine, run.config_hash);
      });
      els.runsList.appendChild(btn);
    }
    highlightActiveRun();
    syncCompareSelects();
  } catch (err) {
    els.runsList.innerHTML = `<p class="placeholder" style="color:var(--danger)">${err.message}</p>`;
  }
}

function runKey(engine, hash) {
  return `${engine}|${hash}`;
}

function pickCompareRun(engine, hash) {
  const key = runKey(engine, hash);
  if (!state.compareA) state.compareA = key;
  else if (!state.compareB || state.compareB === key) state.compareB = key;
  else {
    state.compareA = key;
    state.compareB = null;
  }
  syncCompareSelects();
  loadRuns();
  setStatus(`Compare: A=${state.compareA || "—"} B=${state.compareB || "—"}`);
}

function syncCompareSelects() {
  if (!els.compareRunA || !els.compareRunB) return;
  const opts = state.savedRuns.map((r) => ({
    value: runKey(r.engine, r.config_hash),
    label: `${r.engine}_${r.config_hash}`,
  }));
  for (const sel of [els.compareRunA, els.compareRunB]) {
    const cur = sel.value;
    sel.innerHTML = '<option value="">—</option>' +
      opts.map((o) => `<option value="${o.value}">${o.label}</option>`).join("");
    if (cur && opts.some((o) => o.value === cur)) sel.value = cur;
  }
  if (state.compareA) els.compareRunA.value = state.compareA;
  if (state.compareB) els.compareRunB.value = state.compareB;
}

async function compareSelectedRuns() {
  const a = els.compareRunA?.value;
  const b = els.compareRunB?.value;
  if (!a || !b) {
    setStatus("Select two saved runs to compare.", true);
    return;
  }
  if (a === b) {
    setStatus("Pick two different runs.", true);
    return;
  }
  const [ea, ha] = a.split("|");
  const [eb, hb] = b.split("|");
  setBusy(true);
  try {
    const data = await api("/api/compare/runs", {
      method: "POST",
      body: JSON.stringify({
        engine_a: ea,
        config_hash_a: ha,
        engine_b: eb,
        config_hash_b: hb,
      }),
    });
    renderCompareResults(data);
    setStatus(`Compared ${ea}_${ha} vs ${eb}_${hb}`);
  } catch (err) {
    setStatus(String(err.message), true);
  } finally {
    setBusy(false);
  }
}

function renderCompareResults(data) {
  if (!els.compareResults || !els.compareResultsBody) return;
  els.compareResults.classList.remove("hidden");
  const warnHtml = [
    data.warnings_new?.length
      ? `<p class="compare-warn-new"><strong>New warnings:</strong> ${data.warnings_new.join("; ")}</p>`
      : "",
    data.warnings_resolved?.length
      ? `<p class="compare-warn-resolved"><strong>Resolved:</strong> ${data.warnings_resolved.join("; ")}</p>`
      : "",
  ].join("");
  els.compareResultsBody.innerHTML = `
    <p class="form-hint">${data.a?.outdir || "A"} vs ${data.b?.outdir || "B"}</p>
    ${warnHtml}
    <h4 class="compare-subhead">Result deltas</h4>
    ${window.StudioP2 ? StudioP2.renderDiffTable(data.result_diff) : ""}
    <details class="compare-config-details">
      <summary>Config diff (${data.config_diff?.length || 0} rows)</summary>
      ${window.StudioP2 ? StudioP2.renderDiffTable(data.config_diff) : ""}
    </details>
  `;
}

async function loadCampaigns() {
  if (!els.campaignsList) return;
  els.campaignsList.innerHTML = '<p class="placeholder">Loading…</p>';
  try {
    const items = await api("/api/campaigns/list");
    if (!items.length) {
      els.campaignsList.innerHTML = '<p class="placeholder">No campaigns found.</p>';
      return;
    }
    els.campaignsList.innerHTML = "";
    for (const c of items) {
      const row = document.createElement("div");
      row.className = "campaign-row";
      row.innerHTML = `
        <div class="campaign-name">${c.name}</div>
        <div class="campaign-meta">${c.n_configs} configs</div>
      `;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-campaign-run";
      btn.textContent = "Run";
      btn.title = c.path;
      btn.addEventListener("click", () => runCampaign(c.path));
      row.appendChild(btn);
      els.campaignsList.appendChild(row);
    }
  } catch (err) {
    els.campaignsList.innerHTML = `<p class="placeholder" style="color:var(--danger)">${err.message}</p>`;
  }
}

async function runCampaign(path) {
  if (!window.confirm(`Run campaign ${path}? This may take a while.`)) return;
  setBusy(true);
  try {
    const data = await api("/api/campaigns/run", {
      method: "POST",
      body: JSON.stringify({ campaign_path: path }),
    });
    setStatus(`Campaign "${data.name}" → ${data.outdir} (${data.n_configs} configs)`);
    await loadRuns();
  } catch (err) {
    setStatus(String(err.message), true);
  } finally {
    setBusy(false);
  }
}

function renderSessionNavs() {
  if (!window.StudioP2) return;
  const renderList = (el, paths, emptyMsg) => {
    if (!el) return;
    const valid = paths.filter((p) => state.configs.some((c) => c.path === p));
    if (!valid.length) {
      el.innerHTML = `<p class="placeholder">${emptyMsg}</p>`;
      return;
    }
    el.innerHTML = "";
    for (const path of valid) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "nav-item";
      btn.textContent = configLabel(path);
      btn.title = path;
      btn.addEventListener("click", () => selectConfig(path));
      el.appendChild(btn);
    }
  };
  renderList(els.pinnedNav, StudioP2.loadList(StudioP2.PINNED_KEY), "Pin configs from the list below.");
  renderList(els.recentNav, StudioP2.loadList(StudioP2.RECENT_KEY), "—");
}

async function openRun(engine, configHash) {
  if (!confirmLeaveIfDirty()) return;
  setBusy(true);
  try {
    const data = await api(`/api/runs/${engine}/${configHash}`);
    state.plotSource = "saved";
    renderRun(data);
    if (data.config && state.editor) {
      state.activeConfig = null;
      highlightConfigNav();
      if (els.activeConfigPath) {
        els.activeConfigPath.textContent = data.config_source || `${data.outdir}/config_resolved.yaml`;
      }
      applyEditorPayload(
        {
          config_path: data.config_source || `${data.outdir}/config_resolved.yaml`,
          config_source: data.config_source,
          config: data.config,
          engine: data.engine,
          analysis_mode: data.analysis_mode,
          config_hash: data.config_hash,
          writable: data.writable,
          save_path: data.save_path,
          is_override: data.is_override,
        },
        { isRun: true }
      );
      await validateEditorConfig(state.editor.getConfig(), { silent: true });
    }
    setStatus(`Opened ${data.engine}_${data.config_hash}`);
  } catch (err) {
    setStatus(String(err.message), true);
  } finally {
    setBusy(false);
  }
}

function renderProjectNav(projects) {
  if (!els.configNav) return;
  const expanded = new Set(JSON.parse(localStorage.getItem(EXPANDED_PROJECTS_KEY) || "[]"));
  els.configNav.innerHTML = "";

  if (!projects.length) {
    els.configNav.innerHTML = '<p class="placeholder">No projects yet. Click + to create one.</p>';
    return;
  }

  for (const project of projects) {
    const block = document.createElement("details");
    block.className = "nav-project";
    block.dataset.project = project.slug;
    block.open = expanded.has(project.slug) || project.configs.some((c) => c.path === state.activeConfig);

    const summary = document.createElement("summary");
    summary.className = "nav-project-header";
    summary.innerHTML = `
      <span class="nav-chevron" aria-hidden="true"></span>
      <span class="nav-project-label">
        <span class="nav-project-name">${project.name}</span>
        <span class="nav-project-meta">${project.configs.length} cfg</span>
      </span>
    `;

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn-icon btn-add-config";
    addBtn.textContent = "+";
    addBtn.title = "New config in this project";
    addBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      openCreateConfigDialog(project);
    });
    summary.appendChild(addBtn);
    block.appendChild(summary);

    if (project.description) {
      const desc = document.createElement("p");
      desc.className = "nav-project-desc form-hint";
      desc.textContent = project.description;
      block.appendChild(desc);
    }

    const list = document.createElement("div");
    list.className = "nav-project-configs";
    for (const item of project.configs) {
      const row = document.createElement("div");
      row.className = "nav-item-row";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "nav-item";
      btn.dataset.config = item.path;
      const label = item.filename?.replace(/\.ya?ml$/i, "") || item.name;
      btn.innerHTML = item.is_primary
        ? `<span class="cfg-name">${label}</span><span class="cfg-badge">primary</span>`
        : `<span class="cfg-name">${label}</span>`;
      btn.title = item.path;
      btn.addEventListener("click", () => selectConfig(item.path));
      const pin = document.createElement("button");
      pin.type = "button";
      pin.className = "btn-pin" + (window.StudioP2?.isPinned(item.path) ? " is-pinned" : "");
      pin.textContent = "★";
      pin.title = "Pin config";
      pin.addEventListener("click", (e) => {
        e.stopPropagation();
        if (window.StudioP2) {
          const pinned = StudioP2.togglePin(item.path);
          pin.classList.toggle("is-pinned", pinned);
          renderSessionNavs();
        }
      });
      row.appendChild(btn);
      row.appendChild(pin);
      list.appendChild(row);
    }
    block.appendChild(list);

    block.addEventListener("toggle", () => {
      if (block.open) expanded.add(project.slug);
      else expanded.delete(project.slug);
      localStorage.setItem(EXPANDED_PROJECTS_KEY, JSON.stringify([...expanded]));
    });

    els.configNav.appendChild(block);
  }

  renderSessionNavs();
  highlightConfigNav();

  els.configPath.innerHTML = "";
  for (const item of state.configs) {
    const opt = document.createElement("option");
    opt.value = item.path;
    opt.textContent = item.path;
    els.configPath.appendChild(opt);
  }
}

function openCreateProjectDialog() {
  els.formNewProject?.reset();
  els.dialogNewProject?.showModal();
}

function openCreateConfigDialog(project) {
  state.createConfigProject = project;
  if (els.newConfigProjectLabel) {
    els.newConfigProjectLabel.textContent = `Project: ${project.name} (${project.slug})`;
  }
  els.formNewConfig?.reset();
  els.dialogNewConfig?.showModal();
}

async function submitNewProject(e) {
  e.preventDefault();
  const fd = new FormData(els.formNewProject);
  const name = String(fd.get("name") || "").trim();
  const slug = String(fd.get("slug") || "").trim() || null;
  const description = String(fd.get("description") || "").trim();
  if (!name) return;
  setBusy(true);
  try {
    const data = await api("/api/projects/create", {
      method: "POST",
      body: JSON.stringify({ name, slug, description }),
    });
    els.dialogNewProject?.close();
    await loadProjects();
    if (data.default_config) selectConfig(data.default_config);
    setStatus(`Created project ${data.name}`);
  } catch (err) {
    setStatus(String(err.message), true);
  } finally {
    setBusy(false);
  }
}

async function submitNewConfig(e) {
  e.preventDefault();
  const project = state.createConfigProject;
  if (!project) return;
  const fd = new FormData(els.formNewConfig);
  const name = String(fd.get("name") || "").trim();
  const mode = String(fd.get("mode") || "design");
  if (!name) return;
  setBusy(true);
  try {
    const data = await api(`/api/projects/${encodeURIComponent(project.slug)}/configs`, {
      method: "POST",
      body: JSON.stringify({ name, mode }),
    });
    els.dialogNewConfig?.close();
    await loadProjects();
    if (data.config_path) selectConfig(data.config_path);
    setStatus(`Created ${data.config_path}`);
  } catch (err) {
    setStatus(String(err.message), true);
  } finally {
    setBusy(false);
  }
}

function renderConfigNav(configs) {
  renderProjectNav(state.projects);
}

async function loadEditorConfig() {
  const path = state.activeConfig || els.configPath.value;
  if (!path || !state.editor) return;
  const loadId = ++state.loadSeq;
  state.configLoading = true;
  updateEditUI();
  try {
    let data;
    try {
      data = await api(`/api/config/resolve?config_path=${encodeURIComponent(path)}`);
    } catch (err) {
      if (!String(err.message).includes("Not Found")) throw err;
      data = await api("/api/config/resolve/path", {
        method: "POST",
        body: JSON.stringify({ config_path: path }),
      });
    }
    if (loadId !== state.loadSeq) return;
    state.activeConfig = path;
    if (els.activeConfigPath) els.activeConfigPath.textContent = path;
    highlightConfigNav();
    applyEditorPayload(data);
    await validateEditorConfig(state.editor.getConfig(), { silent: true });
    if (loadId === state.loadSeq) setStatus("");
  } catch (err) {
    if (loadId !== state.loadSeq) return;
    const msg = String(err.message);
    if (msg.includes("Not Found") && msg.includes("resolve")) {
      state.editor.setValidation(false, "Restart server");
      setStatus("Restart Studio: python -m resa_studio", true);
      return;
    }
    if (state.editor?.showLoadError) {
      state.editor.showLoadError(path, msg);
    } else {
      state.editor?.setValidation(false, msg.slice(0, 100));
    }
    setStatus(msg, true);
  } finally {
    if (loadId === state.loadSeq) {
      state.configLoading = false;
      updateEditUI();
    }
  }
}

let runSeq = 0;
async function refreshResultsFromConfig({ quiet = true, busy = false } = {}) {
  const config = state.editor?.getConfig();
  if (!config) return;
  const seq = ++runSeq;
  if (busy) setBusy(true);
  try {
    const data = await api("/api/runs/fast", {
      method: "POST",
      body: JSON.stringify({ config }),
    });
    if (seq !== runSeq) return;
    state.plotSource = "live";
    renderRun(data);
    if (!quiet) setStatus(`${data.engine} · ${data.config_hash}`);
  } catch (err) {
    if (seq !== runSeq) return;
    if (!quiet) setStatus(String(err.message), true);
  } finally {
    if (busy) setBusy(false);
  }
}

let validateSeq = 0;
async function validateEditorConfig(config, { silent = false, autoRun = false } = {}) {
  if (!config || !state.editor) return null;
  const seq = ++validateSeq;
  const result = await validateConfigApi(config);
  if (seq !== validateSeq) return result.ok ? result.data : null;
  if (result.ok) {
    const data = result.data;
    state.editor.setValidation(true, `${data.engine} · ${data.mode} · ${data.config_hash}`, []);
    if (!silent) setStatus(`Valid · hash ${data.config_hash}`);
    if (autoRun && els.autoRun?.checked && state.editSession?.editing) {
      await refreshResultsFromConfig({ quiet: true });
    }
    updateEditUI();
    return data;
  }
  const errCount = result.errors.length;
  const shortMsg = errCount
    ? `${errCount} validation error${errCount > 1 ? "s" : ""}`
    : result.message.slice(0, 100);
  state.editor.setValidation(false, shortMsg, result.errors);
  if (!silent && result.errors.length) {
    const tab = state.editor._tabForPath(result.errors[0].loc || []);
    if (tab) {
      state.editor.activeTab = tab;
      state.editor._render();
      requestAnimationFrame(() => {
        const key = state.editor._errorFieldPath(result.errors[0].loc || []);
        const el = state.editor.container.querySelector(`[data-config-path="${key}"]`);
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        el?.focus?.();
      });
    }
  }
  if (!silent) setStatus(result.message, true);
  updateEditUI();
  return null;
}

async function loadProjects() {
  state.projects = await api("/api/projects/list");
  state.configs = state.projects.flatMap((p) =>
    p.configs.map((c) => ({
      ...c,
      project: p.slug,
      project_name: p.name,
    }))
  );
  renderProjectNav(state.projects);
  return state.projects;
}

async function loadConfigs() {
  await loadProjects();
  const initial = state.configs.some((c) => c.path === DEFAULT_CONFIG)
    ? DEFAULT_CONFIG
    : state.configs[0]?.path;
  if (initial && !state.activeConfig) selectConfig(initial);
}

async function checkHealth() {
  const data = await api("/api/health");
  els.health.textContent = `API ${data.status} · v${data.version}`;
  els.health.classList.add("ok");
}

async function validateConfig() {
  setBusy(true);
  try {
    await validateEditorConfig(state.editor?.getConfig());
  } finally {
    setBusy(false);
  }
}

async function run(mode, { quiet = false } = {}) {
  if (mode === "fast") {
    await refreshResultsFromConfig({ quiet, busy: true });
    return;
  }
  setBusy(true);
  try {
    const config = state.editor?.getConfig();
    if (!config) throw new Error("Select a config first");
    const data = await api("/api/runs/full", {
      method: "POST",
      body: JSON.stringify({ config }),
    });
    state.plotSource = "saved";
    renderRun(data);
    if (!quiet) setStatus(`${data.mode} · ${data.engine} · ${data.config_hash}`);
    await loadRuns();
  } catch (err) {
    if (!quiet) setStatus(String(err.message), true);
  } finally {
    setBusy(false);
  }
}

els.btnValidate.addEventListener("click", validateConfig);
els.btnRunFast.addEventListener("click", () => run("fast"));
els.btnRunFull.addEventListener("click", () => run("full"));
els.btnRefreshRuns.addEventListener("click", loadRuns);
els.btnRefreshCampaigns?.addEventListener("click", loadCampaigns);
els.btnNewProject?.addEventListener("click", openCreateProjectDialog);
els.formNewProject?.addEventListener("submit", submitNewProject);
els.formNewConfig?.addEventListener("submit", submitNewConfig);
for (const dlg of [els.dialogNewProject, els.dialogNewConfig]) {
  dlg?.querySelectorAll(".btn-dialog-cancel").forEach((btn) => {
    btn.addEventListener("click", () => dlg.close());
  });
}
els.btnCompareRuns?.addEventListener("click", compareSelectedRuns);
els.compareRunA?.addEventListener("change", () => { state.compareA = els.compareRunA.value || null; });
els.compareRunB?.addEventListener("change", () => { state.compareB = els.compareRunB.value || null; });
els.btnEdit?.addEventListener("click", enterEditMode);
els.btnSave?.addEventListener("click", saveEdit);
els.btnCancel?.addEventListener("click", cancelEdit);
els.btnTheme?.addEventListener("click", toggleTheme);

(async function init() {
  try {
    applyTheme(getTheme());
    await checkHealth();
    state.editor = new ConfigEditor(els.configEditor, {
      onChange: (config) => {
        if (state.editSession?.editing) {
          validateEditorConfig(config, { silent: true, autoRun: true });
        }
      },
      onDirty: (dirty) => markDirty(dirty),
    });
    await state.editor.loadSchema();
    await Promise.all([loadConfigs(), loadRuns(), loadCampaigns()]);
  } catch (err) {
    els.health.textContent = "API offline";
    els.health.style.color = "var(--danger)";
    setStatus(String(err.message), true);
  }
})();
