/**
 * Schema-driven config editor — tabbed sections, flat form grids.
 */
(function () {
  const FIELD_LABELS = {
    engine: "Engine name",
    description: "Description",
    thrust_N: "Thrust (N)",
    pc_bar: "Chamber pressure (bar)",
    eta_cstar: "η c*",
    eta_cstar_tol: "η c* tolerance",
    eta_cf: "η CF",
    p_amb_bar: "Ambient / back pressure (bar)",
    of_ratio: "O/F ratio",
    pe_bar: "Design exit pressure pe (bar)",
    eps: "Area ratio ε",
    mdot_ox_kg_s: "Ox mass flow (kg/s)",
    mdot_fuel_kg_s: "Fuel mass flow (kg/s)",
    throat_diameter_m: "Throat diameter (m)",
    exit_diameter_m: "Exit diameter (m)",
    name: "Propellant set label",
    oxidizer: "Oxidizer",
    fuel: "Fuel",
    cea_oxidizer: "CEA oxidizer name",
    cea_fuel: "CEA fuel name",
    ox_temp_K: "Ox temperature (K)",
    fuel_temp_K: "Fuel temperature (K)",
    backend: "Backend",
    contraction_ratio: "Contraction ratio",
    l_star_m: "L* (m)",
    contour: "Contour type",
    bell_fraction: "Bell fraction",
    n_channels: "Channel count",
    bartz_correction: "Bartz correction factor",
    n_stations: "Contour stations",
    coolant_fraction: "Coolant mass fraction",
    channel_width_m: "Channel width (m)",
    channel_height_m: "Channel height (m)",
    rib_width_m: "Rib width (m)",
    inner_wall_thickness_m: "Wall thickness (m)",
    inlet_T_K: "Coolant inlet T (K)",
    inlet_p_bar: "Coolant inlet p (bar)",
    coolant: "Coolant",
    wall_material: "Wall material",
    mdot_coolant_kg_s: "Coolant mdot override (kg/s)",
    correlation: "Heat-transfer correlation",
    ox_fraction: "Ox fraction range",
    of_range: "O/F range",
    throttle_fraction: "Throttle range",
    n: "Grid points",
  };

  const SECTIONS = [
    { id: "design", title: "Design", keys: ["operating_point"], modes: ["design"], default: true },
    { id: "analyze", title: "Analyze", keys: ["geometry", "analyze_point"], modes: ["analyze"] },
    { id: "propellants", title: "Propellants", keys: ["propellants"] },
    { id: "combustion", title: "Combustion", keys: ["combustion"] },
    { id: "chamber", title: "Chamber", keys: ["chamber"] },
    { id: "cooling", title: "Regen cooling", keys: ["cooling", "regen"] },
    { id: "offdesign", title: "Off-design", keys: ["offdesign"] },
  ];

  const CHAMBER_UI_SKIP = new Set(["bartz_correction", "n_stations"]);
  const CHAMBER_CONTOUR_KEYS = [
    "contraction_ratio", "l_star_m", "contour", "bell_fraction",
    "throat_diameter_m", "exit_diameter_m",
  ];
  const CORRELATION_HINTS = {
    gnielinski: "Turbulent internal flow — good default for channel Reynolds 2300–5e5.",
    chen: "Subcooled boiling / nucleate regime — use when wall exceeds saturation.",
    jackson: "Supercritical pressure — enhanced HTC near pseudo-critical temperature.",
  };
  const COOLING_CHAMBER_FIELDS = ["bartz_correction", "n_stations"];
  const COOLING_DIM_KEYS = new Set([
    "channel_width_m", "channel_height_m", "rib_width_m", "inner_wall_thickness_m",
  ]);
  const COOLING_SECTIONS = [
    {
      title: "Coolant & inlet",
      hint: "Coolant species and manifold conditions at the channel inlet. Leave mdot blank to use engine propellant flows.",
      keys: ["coolant", "inlet_T_K", "inlet_p_bar", "mdot_coolant_kg_s"],
    },
    {
      title: "Channel layout (throat reference)",
      hint: "Scalar channel dimensions at the throat circumference. Use the preview to verify fit and pitch.",
      keys: ["channel_width_m", "channel_height_m", "rib_width_m", "inner_wall_thickness_m"],
    },
    {
      title: "Wall & heat transfer",
      hint: "Material properties and tube-side correlation for the regen thermal model.",
      keys: ["wall_material", "correlation"],
    },
    {
      title: "Discretization & Bartz",
      hint: "Contour sampling and hot-gas heat-transfer correction applied along the chamber.",
      chamberKeys: COOLING_CHAMBER_FIELDS,
    },
  ];
  const TAB_CONFIG_KEYS = {
    design: ["engine", "description", "operating_point"],
    analyze: ["geometry", "analyze_point"],
    propellants: ["propellants"],
    combustion: ["combustion"],
    chamber: ["chamber"],
    cooling: ["cooling"],
    offdesign: ["offdesign"],
    regen: ["regen"],
  };

  const DRAFT_STORAGE_PREFIX = "resa-studio-draft:";
  const SKIP_KEYS = new Set(["config_hash", "table", "cea_oxidizer", "cea_fuel"]);

  function labelFor(key) {
    return FIELD_LABELS[key] || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  class SchemaResolver {
    constructor(schema) {
      this.defs = schema.$defs || {};
    }

    resolve(node) {
      if (!node) return { type: "unknown" };
      if (node.$ref) {
        return this.resolve(this.defs[node.$ref.replace("#/$defs/", "")] || {});
      }
      if (node.anyOf) {
        const variants = node.anyOf.filter((v) => v.type !== "null");
        if (variants.length === 1) {
          return { ...this.resolve(variants[0]), nullable: true, default: node.default };
        }
      }
      return node;
    }

    propSchema(parentSchema, key) {
      const raw = parentSchema.properties?.[key];
      return raw ? this.resolve(raw) : null;
    }
  }

  class ConfigEditor {
    constructor(container, callbacks = {}) {
      this.container = container;
      this.onChange = callbacks.onChange || (() => {});
      this.onDirty = callbacks.onDirty || (() => {});
      this.config = null;
      this.mode = "design";
      this.activeTab = "design";
      this.editable = false;
      this.validationState = { ok: null, message: "" };
      this.validationErrors = [];
      this._editBaseline = null;
      this._history = [];
      this._historyIdx = -1;
      this._historyPaused = false;
      this._debouncedNotify = debounce(() => {
        this._pushHistory();
        this.onChange(this.getConfig(), this.meta);
        if (this.workspace) this.workspace.onConfigChange();
      }, 500);
      this.workspace = window.DesignWorkspace ? new window.DesignWorkspace(this) : null;
      this._nChannelsAuto = false;
    }

    async loadSchema() {
      const res = await fetch("/api/config/schema");
      if (!res.ok) throw new Error("Failed to load config schema");
      this.schema = await res.json();
      this.resolver = new SchemaResolver(this.schema);
    }

    loadConfig(payload) {
      this.config = structuredClone(payload.config);
      this.mode = payload.mode;
      this.activeTab = this.mode === "design" ? "design" : "analyze";
      this.editable = false;
      this.meta = {
        config_path: payload.config_path,
        config_hash: payload.config_hash,
        engine: payload.engine,
        writable: !!payload.writable,
        save_path: payload.save_path || payload.config_path,
        is_override: !!payload.is_override,
      };
      this.validationState = { ok: null, message: "—" };
      this._render();
      this._emitChange(true);
      if (this.workspace) this.workspace.refresh();
    }

    showLoadError(configPath, message) {
      this.config = null;
      this.mode = "design";
      this.editable = false;
      this.meta = {
        config_path: configPath,
        config_hash: null,
        engine: null,
        writable: true,
        save_path: configPath,
        is_override: false,
      };
      this.validationState = { ok: false, message };
      const esc = (s) => String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      this.container.innerHTML = `
        <div class="load-error-panel">
          <p class="load-error-title">Could not load config</p>
          <p class="load-error-path"><code>${esc(configPath)}</code></p>
          <pre class="load-error-detail">${esc(message)}</pre>
          <p class="form-hint">Fix the YAML on disk. If the editor still shows the wrong engine after a fix, hard-refresh or clear the browser draft for this path.</p>
        </div>`;
      this._emitChange(true);
    }

    setEditable(editable) {
      this.editable = editable;
      if (editable) {
        this._editBaseline = structuredClone(this.config);
        this._history = [this.getSnapshot()];
        this._historyIdx = 0;
        this._bindUndoRedo();
        this._offerDraftRestore();
      } else {
        this._editBaseline = null;
        this._history = [];
        this._historyIdx = -1;
      }
      if (this.config) this._render();
    }

    revertTo(payload) {
      this.config = structuredClone(payload.config);
      this.mode = payload.mode;
      this.activeTab = this.mode === "design" ? "design" : "analyze";
      this.editable = false;
      this.container.classList.remove("is-editing");
      this._render();
      this.onDirty(false);
      this._emitChange(true);
      if (this.workspace) this.workspace.refresh();
    }

    getConfig() {
      if (!this.config) return null;
      const out = structuredClone(this.config);
      delete out.config_hash;
      if (this.mode === "design") {
        out.analyze_point = null;
        out.geometry = null;
      } else {
        out.operating_point = null;
      }
      return out;
    }

    getSnapshot() {
      return {
        config: structuredClone(this.config),
        mode: this.mode,
        meta: { ...this.meta },
      };
    }

    setValidation(ok, message, errors = []) {
      this.validationState = { ok, message };
      this.validationErrors = Array.isArray(errors) ? errors : [];
      const badge = document.getElementById("editor-validation");
      if (!badge) return;
      const errCount = this.validationErrors.length;
      badge.textContent = ok === false && errCount
        ? `${errCount} validation error${errCount > 1 ? "s" : ""}`
        : message;
      badge.className = "validation-badge " + (ok ? "ok" : ok === false ? "error" : "");
      badge.title = ok === false && errCount
        ? this.validationErrors.map((e) => `${(e.loc || []).join(".")}: ${e.msg}`).join("\n")
        : message;
      this._applyFieldErrors();
      this._renderConstraintsPanel();
    }

    _pathKey(path) {
      return path.join(".");
    }

    _applyFieldErrors() {
      this.container.querySelectorAll(".form-field.has-error").forEach((el) => {
        el.classList.remove("has-error");
        el.querySelector(".field-error-msg")?.remove();
      });
      for (const err of this.validationErrors) {
        const key = this._errorFieldPath(err.loc);
        if (!key) continue;
        const field = this.container.querySelector(`[data-config-path="${key}"]`)?.closest(".form-field");
        if (!field) continue;
        field.classList.add("has-error");
        const msg = document.createElement("span");
        msg.className = "field-error-msg";
        msg.textContent = err.msg;
        field.appendChild(msg);
      }
    }

    _tabForPath(loc) {
      const parts = [...(loc || [])];
      if (parts[0] === "body") parts.shift();
      if (parts[0] === "config") parts.shift();
      const top = parts[0];
      if (top === "operating_point" || top === "engine" || top === "description") return "design";
      if (top === "geometry" || top === "analyze_point") return "analyze";
      if (TAB_CONFIG_KEYS[top]) return top;
      return null;
    }

    _errorFieldPath(loc) {
      const parts = [...(loc || [])];
      if (parts[0] === "body") parts.shift();
      if (parts[0] === "config") parts.shift();
      return parts.join(".");
    }

    _dirtyTabs() {
      if (!this._editBaseline || !this.config) return new Set();
      const dirty = new Set();
      for (const [tab, keys] of Object.entries(TAB_CONFIG_KEYS)) {
        for (const k of keys) {
          if (JSON.stringify(this.config[k]) !== JSON.stringify(this._editBaseline[k])) {
            dirty.add(tab);
            break;
          }
        }
      }
      return dirty;
    }

    getChangeSummary() {
      if (!this._editBaseline) return [];
      const changes = [];
      const walk = (a, b, prefix) => {
        if (a === b) return;
        if (typeof a !== typeof b || a == null || b == null) {
          if (JSON.stringify(a) !== JSON.stringify(b)) {
            changes.push(prefix.join(".") || "(root)");
          }
          return;
        }
        if (Array.isArray(a) && Array.isArray(b)) {
          if (JSON.stringify(a) !== JSON.stringify(b)) changes.push(prefix.join("."));
          return;
        }
        if (typeof a === "object") {
          const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
          for (const k of keys) walk(a[k], b[k], [...prefix, k]);
          return;
        }
        if (a !== b) changes.push(prefix.join("."));
      };
      walk(this._editBaseline, this.config, []);
      return changes;
    }

    _pushHistory() {
      if (this._historyPaused || !this.editable) return;
      const snap = this.getSnapshot();
      const prev = this._history[this._historyIdx];
      if (prev && JSON.stringify(prev.config) === JSON.stringify(snap.config) &&
          prev.mode === snap.mode) return;
      if (this._historyIdx < this._history.length - 1) {
        this._history = this._history.slice(0, this._historyIdx + 1);
      }
      this._history.push(snap);
      if (this._history.length > 50) this._history.shift();
      this._historyIdx = this._history.length - 1;
      this._saveDraft();
    }

    _undo() {
      if (this._historyIdx <= 0) return;
      this._historyIdx -= 1;
      this._restoreHistory(this._history[this._historyIdx]);
    }

    _redo() {
      if (this._historyIdx >= this._history.length - 1) return;
      this._historyIdx += 1;
      this._restoreHistory(this._history[this._historyIdx]);
    }

    _restoreHistory(snap) {
      this._historyPaused = true;
      this.config = structuredClone(snap.config);
      this.mode = snap.mode;
      this._render();
      this.onDirty(true);
      this._notifyChange(true);
      this._historyPaused = false;
    }

    _bindUndoRedo() {
      if (this._undoBound) return;
      this._undoBound = true;
      this.container.addEventListener("keydown", (e) => {
        if (!this.editable) return;
        if ((e.ctrlKey || e.metaKey) && e.key === "z" && !e.shiftKey) {
          e.preventDefault();
          this._undo();
        } else if ((e.ctrlKey || e.metaKey) && (e.key === "y" || (e.key === "z" && e.shiftKey))) {
          e.preventDefault();
          this._redo();
        }
      });
    }

    _draftKey() {
      return this.meta?.config_path ? `${DRAFT_STORAGE_PREFIX}${this.meta.config_path}` : null;
    }

    _saveDraft() {
      const key = this._draftKey();
      if (!key || !this.editable) return;
      try {
        localStorage.setItem(key, JSON.stringify({
          config: this.config,
          mode: this.mode,
          ts: Date.now(),
        }));
      } catch { /* quota */ }
    }

    _clearDraft() {
      const key = this._draftKey();
      if (key) localStorage.removeItem(key);
    }

    _offerDraftRestore() {
      const key = this._draftKey();
      if (!key) return;
      let raw;
      try { raw = localStorage.getItem(key); } catch { return; }
      if (!raw) return;
      let draft;
      try { draft = JSON.parse(raw); } catch { return; }
      if (!draft?.config) return;
      if (JSON.stringify(draft.config) === JSON.stringify(this.config)) return;
      const when = draft.ts ? new Date(draft.ts).toLocaleString() : "earlier";
      if (!window.confirm(`Restore unsaved draft from ${when}?`)) return;
      this._historyPaused = true;
      this.config = structuredClone(draft.config);
      if (draft.mode) this.mode = draft.mode;
      this._render();
      this.onDirty(true);
      this._notifyChange(true);
      this._historyPaused = false;
      this._pushHistory();
    }

    clearEditSession() {
      this._clearDraft();
      this._editBaseline = null;
    }

    _computeConstraints() {
      const items = [];
      const cfg = this.config;
      const cool = cfg?.cooling;
      const ch = cfg?.chamber;
      if (cool && ch?.throat_diameter_m) {
        const rt = ch.throat_diameter_m / 2;
        const circ = 2 * Math.PI * (rt + (cool.inner_wall_thickness_m || 0));
        const pitch = (cool.channel_width_m || 0) + (cool.rib_width_m || 0);
        const used = (cool.n_channels || 0) * pitch;
        const pct = circ > 0 ? (used / circ) * 100 : null;
        if (pct != null) {
          items.push({
            status: pct > 102 ? "fail" : pct > 96 ? "warn" : "ok",
            text: `Channel layout uses ${pct.toFixed(0)}% of throat circumference`,
            tab: "cooling",
          });
        }
      }
      const warnings = this.workspace?.contourData?.warnings || [];
      for (const w of warnings) {
        items.push({ status: "warn", text: w, tab: "chamber" });
      }
      if (this.workspace?.sectionData?.error) {
        items.push({ status: "fail", text: this.workspace.sectionData.error, tab: "cooling" });
      }
      return items;
    }

    _renderConstraintsPanel() {
      let panel = this.container.querySelector(".constraints-panel");
      if (!panel) {
        panel = document.createElement("details");
        panel.className = "constraints-panel";
        panel.open = true;
        panel.innerHTML = "<summary>Design checks</summary><ul class=\"constraints-list\"></ul>";
        const toolbar = this.container.querySelector(".editor-toolbar");
        if (toolbar) toolbar.after(panel);
        else this.container.prepend(panel);
      }
      const list = panel.querySelector(".constraints-list");
      const items = this._computeConstraints();
      if (!items.length) {
        list.innerHTML = "<li class=\"constraint-ok\">No issues detected.</li>";
        return;
      }
      list.innerHTML = items.map((it) => `
        <li class="constraint-${it.status}">
          <button type="button" class="constraint-jump" data-tab="${it.tab || ""}">${it.text}</button>
        </li>
      `).join("");
      list.querySelectorAll(".constraint-jump").forEach((btn) => {
        btn.addEventListener("click", () => {
          const tab = btn.dataset.tab;
          if (tab) {
            this.activeTab = tab;
            this._render();
          }
        });
      });
    }

    _emitChange(immediate = false) {
      if (!this.editable) return;
      this.onDirty(true);
      this._notifyChange(immediate);
    }

    _applyEditableState() {
      const lock = !this.editable;
      this.container.querySelectorAll(
        "input, select, textarea, button.btn-inline, button.editor-tab"
      ).forEach((el) => {
        if (el.name === "cfg-mode") return;
        if (el.classList.contains("editor-tab")) {
          el.disabled = false;
          return;
        }
        const tag = el.tagName;
        const type = (el.type || "").toLowerCase();
        if (tag === "SELECT" || type === "checkbox" || type === "radio" || type === "button") {
          el.disabled = lock;
          el.readOnly = false;
        } else {
          el.disabled = false;
          el.readOnly = lock;
        }
      });
      this.container.querySelectorAll('input[name="cfg-mode"]').forEach((el) => {
        el.disabled = lock;
      });
      this.container.querySelectorAll(".form-toggle-row input").forEach((el) => {
        el.disabled = lock;
      });
    }

    _setPath(path, value, opts = {}) {
      const { notify = true } = opts;
      let obj = this.config;
      for (let i = 0; i < path.length - 1; i++) {
        const k = path[i];
        if (obj[k] == null) obj[k] = {};
        obj = obj[k];
      }
      const last = path[path.length - 1];
      if (value === undefined) delete obj[last];
      else obj[last] = value;
      if (this.editable) this.onDirty(true);
      if (notify && this.editable) this._notifyChange(false);
    }

    _notifyChange(immediate = false) {
      if (!this.editable) return;
      if (immediate) {
        this._pushHistory();
        this.onChange(this.getConfig(), this.meta);
        if (this.workspace) this.workspace.onConfigChange();
      } else {
        this._debouncedNotify();
      }
    }

    _getPath(path) {
      let obj = this.config;
      for (const k of path) {
        if (obj == null) return undefined;
        obj = obj[k];
      }
      return obj;
    }

    _render() {
      this.container.innerHTML = "";

      const toolbar = document.createElement("div");
      toolbar.className = "editor-toolbar";
      toolbar.innerHTML = `
        <div class="mode-switch" role="radiogroup" aria-label="Analysis mode">
          <label><input type="radio" name="cfg-mode" value="design" ${this.mode === "design" ? "checked" : ""}><span>Design</span></label>
          <label><input type="radio" name="cfg-mode" value="analyze" ${this.mode === "analyze" ? "checked" : ""}><span>Analyze</span></label>
        </div>
      `;
      toolbar.querySelectorAll('input[name="cfg-mode"]').forEach((el) => {
        el.addEventListener("change", () => this._switchMode(el.value));
      });
      this.container.appendChild(toolbar);

      const tabs = document.createElement("div");
      tabs.className = "editor-tabs";
      tabs.setAttribute("role", "tablist");

      const panels = document.createElement("div");
      panels.className = "editor-panels";

      const visibleSections = SECTIONS.filter((s) => {
        if (s.requiresRegen && !this.config.regen) return false;
        if (s.modes && !s.modes.includes(this.mode)) return false;
        return true;
      });

      if (!visibleSections.some((s) => s.id === this.activeTab)) {
        this.activeTab = visibleSections[0]?.id || "design";
      }

      const dirtyTabs = this.editable ? this._dirtyTabs() : new Set();

      for (const sec of visibleSections) {
        const tab = document.createElement("button");
        tab.type = "button";
        tab.className = "editor-tab" + (sec.id === this.activeTab ? " active" : "");
        tab.textContent = sec.title + (dirtyTabs.has(sec.id) ? " •" : "");
        tab.dataset.tab = sec.id;
        tab.setAttribute("role", "tab");
        tab.addEventListener("click", () => {
          this.activeTab = sec.id;
          this._render();
          if (sec.id === "cooling" && this.workspace) {
            this.workspace.prefetchCooling();
            this.workspace._debouncedThermal();
          }
        });
        tabs.appendChild(tab);

        const panel = document.createElement("div");
        panel.className = "editor-panel" + (sec.id === this.activeTab ? " active" : "");
        panel.dataset.panel = sec.id;
        panel.appendChild(this._renderSectionContent(sec));
        panels.appendChild(panel);
      }

      this.container.appendChild(tabs);
      this.container.appendChild(panels);
      this._renderConstraintsPanel();
      this.container.classList.toggle("is-editing", this.editable);
      this._applyEditableState();
      if (this.workspace && (this.activeTab === "chamber" || this.activeTab === "cooling" || this.activeTab === "analyze")) {
        this.workspace.refresh();
      }
    }

    _switchMode(mode) {
      this.mode = mode;
      this.activeTab = mode === "design" ? "design" : "analyze";
      if (mode === "design" && !this.config.operating_point) {
        this.config.operating_point = {
          thrust_N: 10000, pc_bar: 30, eta_cstar: 0.95, eta_cf: 0.98, p_amb_bar: 0, eps: 20,
        };
      }
      if (mode === "analyze") {
        if (!this.config.geometry) this.config.geometry = { throat_diameter_m: 0.05, eps: 20 };
        if (!this.config.analyze_point) {
          this.config.analyze_point = {
            mdot_ox_kg_s: 1, mdot_fuel_kg_s: 0.2, eta_cstar: 0.95, eta_cf: 0.98, p_amb_bar: 0,
          };
        }
      }
      this._render();
      this._emitChange(true);
      if (this.workspace) this.workspace.onConfigChange();
    }

    _renderSectionContent(sec) {
      const wrap = document.createElement("div");

      if (sec.id === "design") return this._renderDesignTab();
      if (sec.id === "analyze") return this._renderAnalyzeTab();
      if (sec.id === "offdesign") return this._renderOffdesignTab();
      if (sec.id === "propellants") return this._renderPropellantsTab();
      if (sec.id === "chamber") return this._renderChamberTab();
      if (sec.id === "cooling") return this._renderCoolingTab();
      if (sec.id === "combustion") return this._renderCombustionTab();

      if (sec.id === "general") {
        wrap.appendChild(this._buildGrid([[["engine", this.config.engine, this.resolver.propSchema(this.schema, "engine")]]]));
        return wrap;
      }

      if (sec.optional) {
        const key = sec.keys[0];
        const enabled = this.config[key] != null;
        const toggle = document.createElement("div");
        toggle.className = "form-toggle-row";
        toggle.innerHTML = `<label><input type="checkbox" ${enabled ? "checked" : ""}> Enable ${sec.title.toLowerCase()} sweeps</label>`;
        toggle.querySelector("input").addEventListener("change", (e) => {
          this.config[key] = e.target.checked
            ? { ox_throttle: { ox_fraction: [0.5, 1.1], n: 25 } }
            : null;
          this._render();
          this._emitChange(true);
        });
        wrap.appendChild(toggle);
        if (!enabled) return wrap;
      }

      const groups = [];
      for (const key of sec.keys) {
        const value = this.config[key];
        if (value == null) continue;
        const schema = this.resolver.propSchema(this.schema, key);
        if (!schema) continue;

        if (key === "combustion") {
          wrap.appendChild(this._renderCombustion(value, schema));
          continue;
        }

        const title = sec.keys.length > 1 ? labelFor(key) : null;
        groups.push(...this._flattenObject([key], value, schema, title));
      }

      if (groups.length) wrap.appendChild(this._buildGrid(groups));
      return wrap;
    }

    _configSection(title, hint) {
      const section = document.createElement("section");
      section.className = "config-section form-section";
      const head = document.createElement("h3");
      head.className = "form-section-title";
      head.textContent = title;
      section.appendChild(head);
      if (hint) {
        const p = document.createElement("p");
        p.className = "form-section-hint";
        p.textContent = hint;
        section.appendChild(p);
      }
      const body = document.createElement("div");
      body.className = "config-section-body";
      section.appendChild(body);
      return { el: section, body };
    }

    _configTabIntro(text) {
      const intro = document.createElement("p");
      intro.className = "config-tab-intro";
      intro.textContent = text;
      return intro;
    }

    _workspaceSplit(formEl, mountFn) {
      const split = document.createElement("div");
      split.className = "workspace-split";
      const formCol = document.createElement("div");
      formCol.className = "workspace-form-col";
      formCol.appendChild(formEl);
      const previewCol = document.createElement("div");
      previewCol.className = "workspace-preview-col";
      split.appendChild(formCol);
      split.appendChild(previewCol);
      if (this.workspace && mountFn) mountFn(previewCol);
      return split;
    }

    _renderDesignTab() {
      const wrap = document.createElement("div");
      wrap.className = "config-tab workspace-design";

      const idSec = this._configSection(
        "Engine identity",
        "Name and short description for this configuration."
      );
      const engineSchema = this.resolver.propSchema(this.schema, "engine");
      const descSchema = this.resolver.propSchema(this.schema, "description") || { type: "string" };
      const idGrid = document.createElement("div");
      idGrid.className = "form-grid";
      idGrid.appendChild(this._formField(["engine"], "engine", this.config.engine, engineSchema));
      idGrid.appendChild(this._formField(["description"], "description", this.config.description || "", descSchema));
      idSec.body.appendChild(idGrid);
      wrap.appendChild(idSec.el);

      const op = this.config.operating_point || {};
      const opSchema = this.resolver.propSchema(this.schema, "operating_point");
      const perfSec = this._configSection(
        "Performance targets",
        "Nominal thrust, chamber pressure, and efficiency assumptions for sizing."
      );
      const groups = [];
      const perfKeys = ["thrust_N", "pc_bar", "eta_cstar", "eta_cstar_tol", "eta_cf"];
      for (const k of perfKeys) {
        const ps = this.resolver.propSchema(opSchema, k);
        if (ps) groups.push({ path: ["operating_point", k], key: k, value: op[k], schema: ps });
      }
      perfSec.body.appendChild(this._buildGrid(groups));
      wrap.appendChild(perfSec.el);

      const envSec = this._configSection(
        "Nozzle environment & expansion",
        "Ambient pressure is the static pressure outside the nozzle (0 = vacuum). " +
          "Expansion is how the nozzle is sized: optimum matches pe to ambient; otherwise set area ratio ε or a fixed exit pressure."
      );
      const envGrid = document.createElement("div");
      envGrid.className = "form-grid";
      envGrid.appendChild(this._formField(
        ["operating_point", "p_amb_bar"], "p_amb_bar", op.p_amb_bar, this.resolver.propSchema(opSchema, "p_amb_bar")
      ));
      envGrid.appendChild(this._optimumField(
        ["operating_point", "of_ratio"], "of_ratio", op.of_ratio,
        this.resolver.propSchema(opSchema, "of_ratio"), "Use optimum O/F (max Isp)"
      ));

      const expMode = this._expansionMode(op);
      const expRow = document.createElement("div");
      expRow.className = "form-field form-field-wide expansion-mode";
      expRow.innerHTML = `<label>Expansion sizing</label>`;
      const modes = document.createElement("div");
      modes.className = "expansion-modes";
      for (const m of [
        { id: "optimum", label: "Optimum (pe = p_amb)" },
        { id: "eps", label: "Fixed area ratio ε" },
        { id: "pe", label: "Fixed exit pressure pe" },
      ]) {
        const lbl = document.createElement("label");
        lbl.innerHTML = `<input type="radio" name="exp-mode" value="${m.id}" ${expMode === m.id ? "checked" : ""}> ${m.label}`;
        modes.appendChild(lbl);
      }
      expRow.appendChild(modes);
      envGrid.appendChild(expRow);

      const epsField = this._formField(
        ["operating_point", "eps"], "eps", op.eps, this.resolver.propSchema(opSchema, "eps")
      );
      epsField.classList.toggle("hidden", expMode !== "eps");
      epsField.dataset.expField = "eps";
      const peField = this._formField(
        ["operating_point", "pe_bar"], "pe_bar", op.pe_bar, this.resolver.propSchema(opSchema, "pe_bar")
      );
      peField.classList.toggle("hidden", expMode !== "pe");
      peField.dataset.expField = "pe";
      envGrid.appendChild(epsField);
      envGrid.appendChild(peField);

      modes.querySelectorAll('input[name="exp-mode"]').forEach((el) => {
        el.addEventListener("change", () => {
          const mode = el.value;
          const pAmb = this.config.operating_point?.p_amb_bar ?? 1.01325;
          if (mode === "optimum" && pAmb === 0) {
            setTimeout(() => {
              alert(
                "Optimum expansion (pe = p_amb) is undefined in vacuum. " +
                  "Set area ratio ε or exit pressure pe instead."
              );
              this._render();
            }, 0);
            return;
          }
          if (mode === "optimum") {
            this._setPath(["operating_point", "eps"], null);
            this._setPath(["operating_point", "pe_bar"], null);
          } else if (mode === "eps") {
            this._setPath(["operating_point", "pe_bar"], null);
            if (op.eps == null) this._setPath(["operating_point", "eps"], 20);
          } else {
            this._setPath(["operating_point", "eps"], null);
            if (op.pe_bar == null) this._setPath(["operating_point", "pe_bar"], 0.5);
          }
          this._render();
          this._emitChange(true);
        });
      });

      wrap.appendChild(envSec.el);
      envSec.body.appendChild(envGrid);
      return wrap;
    }

    _expansionMode(op) {
      if (op.pe_bar != null) return "pe";
      if (op.eps != null) return "eps";
      return "optimum";
    }

    _optimumField(path, key, value, schema, hint) {
      const field = document.createElement("div");
      field.className = "form-field";
      const label = document.createElement("label");
      label.textContent = labelFor(key);
      field.appendChild(label);
      const row = document.createElement("div");
      row.className = "optimum-row";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = value == null;
      cb.title = hint;
      const span = document.createElement("span");
      span.className = "optimum-label";
      span.textContent = hint;
      const inp = this._input(path, key, value, schema);
      inp.disabled = value == null;
      cb.addEventListener("change", () => {
        if (cb.checked) {
          this._setPath(path, null);
        } else {
          const ps = this.resolver.resolve(schema);
          this._setPath(path, ps.default ?? (key === "of_ratio" ? 5 : 20));
        }
        this._render();
        this._emitChange(true);
      });
      row.appendChild(cb);
      row.appendChild(span);
      if (!cb.checked) row.appendChild(inp);
      field.appendChild(row);
      return field;
    }

    _renderAnalyzeTab() {
      const form = document.createElement("div");
      form.className = "config-tab analyze-form";

      form.appendChild(this._configTabIntro(
        "Analyze mode fixes hardware geometry and measured mass flows. RESA computes performance " +
        "at the test point — use this when iterating on an existing engine or test article."
      ));

      const geo = this.config.geometry || {};
      const geoSchema = this.resolver.propSchema(this.schema, "geometry");
      const geoRows = this._flattenObject(["geometry"], geo, geoSchema);
      form.appendChild(this._buildCoolingSection(
        "Hardware geometry",
        "Measured throat and expansion (give area ratio ε or exit diameter, not both).",
        geoRows
      ));

      const ap = this.config.analyze_point || {};
      const apSchema = this.resolver.propSchema(this.schema, "analyze_point");
      const apRows = this._flattenObject(["analyze_point"], ap, apSchema);
      form.appendChild(this._buildCoolingSection(
        "Test point",
        "Measured propellant flows and efficiency assumptions at the operating condition.",
        apRows
      ));

      const note = document.createElement("p");
      note.className = "config-tab-footnote analyze-note";
      note.textContent =
        "Chamber contour, cooling, and off-design sweeps still use the shared blocks in other tabs. " +
        "Run fast to refresh KPIs and off-design mini charts in Results.";
      form.appendChild(note);

      return this._workspaceSplit(form, (col) => {
        if (this.workspace) this.workspace.mountChamberPanel(col);
      });
    }

    _renderOffdesignTab() {
      const wrap = document.createElement("div");
      wrap.className = "config-tab offdesign-form";

      wrap.appendChild(this._configTabIntro(
        "Off-design sweeps vary throttle and mixture ratio around the nominal design point with fixed geometry. " +
        "Enable sweeps below, then run fast — mini charts appear in the Results panel."
      ));

      const enabled = this.config.offdesign != null;
      const master = document.createElement("div");
      master.className = "form-toggle-row";
      master.innerHTML = `<label><input type="checkbox" ${enabled ? "checked" : ""}> Enable off-design analysis</label>`;
      master.querySelector("input").addEventListener("change", (e) => {
        this.config.offdesign = e.target.checked
          ? { ox_throttle: { ox_fraction: [0.5, 1.1], n: 25 } }
          : null;
        this._render();
        this._emitChange(true);
      });
      wrap.appendChild(master);
      if (!enabled) return wrap;

      const od = this.config.offdesign;
      const odSchema = this.resolver.propSchema(this.schema, "offdesign");

      const addSweepSection = (title, hint, key, defaults) => {
        const sec = document.createElement("section");
        sec.className = "config-section form-section offdesign-sweep-section";
        const on = od[key] != null;
        const head = document.createElement("div");
        head.className = "form-toggle-row form-section-head";
        head.innerHTML = `<label><input type="checkbox" ${on ? "checked" : ""}> <strong>${title}</strong></label>`;
        head.querySelector("input").addEventListener("change", (e) => {
          if (e.target.checked) {
            od[key] = { ...defaults };
          } else {
            od[key] = null;
          }
          this._render();
          this._emitChange(true);
        });
        sec.appendChild(head);
        const hintEl = document.createElement("p");
        hintEl.className = "form-section-hint";
        hintEl.textContent = hint;
        sec.appendChild(hintEl);
        if (on) {
          const subSchema = this.resolver.propSchema(odSchema, key);
          const rows = this._flattenObject(["offdesign", key], od[key], subSchema);
          sec.appendChild(this._buildGrid(rows));
        }
        wrap.appendChild(sec);
      };

      addSweepSection(
        "Ox throttle sweep",
        "Vary oxidizer flow with constant fuel (single-side throttling).",
        "ox_throttle",
        { ox_fraction: [0.5, 1.1], n: 25 }
      );
      addSweepSection(
        "O/F sweep",
        "Vary mixture ratio at constant total mass flow.",
        "of_sweep",
        { of_range: [4.0, 8.0], n: 30 }
      );
      addSweepSection(
        "Throttle × O/F envelope",
        "2-D grid over total-flow throttle fraction and O/F.",
        "envelope",
        { throttle_fraction: [0.5, 1.1], of_range: [4.0, 8.0], n: [20, 20] }
      );

      return wrap;
    }

    _renderPropellantsTab() {
      const wrap = document.createElement("div");
      wrap.className = "config-tab";
      const p = this.config.propellants || {};
      const schema = this.resolver.propSchema(this.schema, "propellants");

      wrap.appendChild(this._configTabIntro(
        "The propellant set groups oxidizer and fuel CoolProp names plus delivery temperatures. " +
        "The name field is a label for this combination (not a separate config file path)."
      ));

      const fluidsSec = this._configSection(
        "Propellant fluids",
        "CoolProp species strings and tank/manifold delivery temperatures."
      );
      const groups = this._flattenObject(["propellants"], p, schema);
      const nameRow = groups.find((r) => r.key === "name");
      if (nameRow) nameRow.key = "name";
      fluidsSec.body.appendChild(this._buildGrid(groups));
      wrap.appendChild(fluidsSec.el);

      const summary = document.createElement("div");
      summary.className = "propellant-summary";
      summary.innerHTML = `<div class="form-subhead">Resolved fluids</div>
        <p class="form-hint">Oxidizer: <strong>${p.oxidizer || "—"}</strong> @ ${p.ox_temp_K ?? "—"} K<br>
        Fuel: <strong>${p.fuel || "—"}</strong> @ ${p.fuel_temp_K ?? "—"} K</p>`;
      wrap.appendChild(summary);

      const backend = this.config.combustion?.backend;
      if (backend === "rocketcea") {
        const ceaSec = this._configSection(
          "RocketCEA names",
          "Optional overrides for CEA species strings (defaults from propellant labels)."
        );
        const grid = document.createElement("div");
        grid.className = "form-grid";
        const pSchema = this.resolver.propSchema(this.schema, "propellants");
        for (const k of ["cea_oxidizer", "cea_fuel"]) {
          const ps = this.resolver.propSchema(pSchema, k);
          if (ps) {
            grid.appendChild(this._formField(["propellants", k], k, p[k], ps));
          }
        }
        ceaSec.body.appendChild(grid);
        wrap.appendChild(ceaSec.el);
      }
      return wrap;
    }

    _renderCombustionTab() {
      const wrap = document.createElement("div");
      wrap.className = "config-tab";
      wrap.appendChild(this._configTabIntro(
        "Select the combustion property backend. Table mode uses precomputed CEA data; RocketCEA evaluates properties at runtime."
      ));
      const value = this.config.combustion;
      const schema = this.resolver.propSchema(this.schema, "combustion");
      if (value && schema) {
        wrap.appendChild(this._renderCombustion(value, schema));
      }
      return wrap;
    }

    _renderChamberTab() {
      const form = document.createElement("div");
      form.className = "config-tab chamber-form";
      const ch = this.config.chamber || {};
      const schema = this.resolver.propSchema(this.schema, "chamber");
      const allRows = this._flattenObject(["chamber"], ch, schema).filter(
        (r) => !r.key || !CHAMBER_UI_SKIP.has(r.key)
      );
      const contourRows = this._coolingRowsForKeys(allRows, CHAMBER_CONTOUR_KEYS);
      const otherRows = allRows.filter((r) => !r.key || !CHAMBER_CONTOUR_KEYS.includes(r.key));

      form.appendChild(this._buildCoolingSection(
        "Contour & sizing",
        "Primary inputs for the chamber meridional contour (L*, contraction, bell). Preview updates live.",
        contourRows
      ));
      if (otherRows.length) {
        form.appendChild(this._buildCoolingSection(
          "Advanced chamber",
          "Additional contour and discretization parameters.",
          otherRows
        ));
      }
      return this._workspaceSplit(form, (col) => {
        if (this.workspace) this.workspace.mountChamberPanel(col);
      });
    }

    _renderCoolingTab() {
      const page = document.createElement("div");
      page.className = "config-tab regen-design-page";

      const RD = window.RegenDesign;
      if (RD) {
        page.appendChild(RD.buildForm(this, this.workspace));
      } else {
        page.innerHTML = '<p class="optional-empty">Regen design module failed to load.</p>';
      }

      const previewMount = document.createElement("div");
      previewMount.className = "regen-design-previews";
      page.appendChild(previewMount);

      if (this.workspace) {
        this.workspace.mountRegenDesignPanel(previewMount, this);
      }

      return page;
    }

    _coolingRowsForKeys(allRows, keys) {
      const byKey = new Map();
      for (const row of allRows) {
        if (row.key) byKey.set(row.key, row);
      }
      return keys.map((k) => byKey.get(k)).filter(Boolean);
    }

    _buildCoolingSection(title, hint, rows) {
      const { el: section, body } = this._configSection(title, hint);
      const grid = document.createElement("div");
      grid.className = "form-grid";
      for (const row of rows) {
        if (row.optional || row.nullableObject) {
          grid.appendChild(this._buildGrid([row]).firstElementChild);
          continue;
        }
        const field = COOLING_DIM_KEYS.has(row.key)
          ? this._formDimField(row.path, row.key, row.value, row.schema)
          : this._formField(row.path, row.key, row.value, row.schema);
        grid.appendChild(field);
      }
      body.appendChild(grid);
      return section;
    }

    _buildChannelCountRow(cool) {
      const nRow = document.createElement("div");
      nRow.className = "form-field form-field-wide";
      nRow.innerHTML = `<label>${labelFor("n_channels")}</label>`;
      const nWrap = document.createElement("div");
      nWrap.className = "channel-count-row";
      const nInp = document.createElement("input");
      nInp.type = "number";
      nInp.min = "4";
      nInp.step = "1";
      nInp.value = cool.n_channels ?? "";
      nInp.disabled = this._nChannelsAuto;
      const autoLbl = document.createElement("label");
      autoLbl.className = "toggle-inline";
      const autoCb = document.createElement("input");
      autoCb.type = "checkbox";
      autoCb.checked = this._nChannelsAuto;
      autoLbl.appendChild(autoCb);
      autoLbl.appendChild(document.createTextNode(" Auto-fit to throat diameter"));
      autoCb.addEventListener("change", async () => {
        this._nChannelsAuto = autoCb.checked;
        nInp.disabled = this._nChannelsAuto;
        if (this._nChannelsAuto && window.postPreview) {
          try {
            const r = await window.postPreview("cooling/suggest-channels", this.getConfig());
            this._setPath(["cooling", "n_channels"], r.n_channels);
            nInp.value = r.n_channels;
          } catch { /* ignore */ }
        }
        this._emitChange(true);
      });
      nInp.addEventListener("input", () => {
        const v = parseInt(nInp.value, 10);
        if (!Number.isNaN(v)) this._setPath(["cooling", "n_channels"], v);
      });
      nInp.addEventListener("change", async () => {
        if (this._nChannelsAuto && window.postPreview) {
          try {
            const r = await window.postPreview("cooling/suggest-channels", this.getConfig());
            this._setPath(["cooling", "n_channels"], r.n_channels);
            nInp.value = r.n_channels;
          } catch { /* ignore */ }
        }
        this._notifyChange(true);
      });
      nWrap.appendChild(nInp);
      nWrap.appendChild(autoLbl);
      nRow.appendChild(nWrap);
      return nRow;
    }

    _buildLayoutSummary(cool, ch) {
      const row = document.createElement("div");
      row.className = "form-field form-field-wide cooling-layout-summary";
      const w = cool.channel_width_m || 0;
      const rib = cool.rib_width_m || 0;
      const n = cool.n_channels || 0;
      const pitch = w + rib;
      const layoutArc = n * pitch;
      const rt = (ch.throat_diameter_m || 0) / 2;
      const throatCirc = rt > 0 ? 2 * Math.PI * rt : 0;
      const fillPct = throatCirc > 0 ? (layoutArc / throatCirc) * 100 : null;
      const parts = [
        `Pitch w+s = ${(pitch * 1000).toFixed(2)} mm`,
        `Layout arc = ${(layoutArc * 1000).toFixed(1)} mm`,
      ];
      if (fillPct != null) {
        parts.push(`≈ ${fillPct.toFixed(0)}% of throat circumference`);
      }
      row.innerHTML = `<label>Layout check</label><p class="layout-summary-text">${parts.join(" · ")}</p>`;
      return row;
    }

    _formDimField(path, key, value, schema) {
      const field = this._formField(path, key, value, schema);
      const inp = field.querySelector("input");
      const hint = document.createElement("span");
      hint.className = "field-unit-hint";
      const updateHint = () => {
        const v = inp ? parseFloat(inp.value) : value;
        hint.textContent = !Number.isNaN(v) && v != null ? `= ${(v * 1000).toFixed(2)} mm` : "";
      };
      updateHint();
      if (inp) inp.addEventListener("input", updateHint);
      field.appendChild(hint);
      return field;
    }

    _flattenObject(path, value, schema, subhead = null) {
      const rows = [];
      if (subhead) rows.push({ subhead });

      const resolved = this.resolver.resolve(schema);
      const props = resolved.properties || {};
      const required = new Set(resolved.required || []);

      for (const [prop, propRaw] of Object.entries(props)) {
        if (SKIP_KEYS.has(prop)) continue;
        if (path[0] === "chamber" && CHAMBER_UI_SKIP.has(prop)) continue;
        if (path[0] === "cooling" && prop === "n_channels") continue;
        const propSchema = this.resolver.resolve(propRaw);
        const propPath = [...path, prop];
        const propValue = value?.[prop];
        const isOptional = propSchema.nullable || !required.has(prop);

        if (propSchema.type === "object" && propSchema.properties) {
          if (isOptional && (propValue == null)) {
            rows.push({ nullableObject: true, path: propPath, key: prop, schema: propSchema });
            continue;
          }
          rows.push(...this._flattenObject(propPath, propValue ?? {}, propSchema, labelFor(prop)));
          continue;
        }

        if (isOptional && (propValue == null || propValue === undefined)) {
          rows.push({ optional: true, path: propPath, key: prop, schema: propSchema });
          continue;
        }

        rows.push({ path: propPath, key: prop, value: propValue, schema: propSchema });
      }
      return rows;
    }

    _buildGrid(rows) {
      const grid = document.createElement("div");
      grid.className = "form-grid";

      for (const row of rows) {
        if (row.subhead) {
          const h = document.createElement("div");
          h.className = "form-subhead";
          h.textContent = row.subhead;
          grid.appendChild(h);
          continue;
        }

        if (row.nullableObject) {
          const el = document.createElement("div");
          el.className = "form-field form-field-wide";
          el.innerHTML = `<label>${labelFor(row.key)}</label>`;
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn-inline";
          btn.textContent = `Add ${labelFor(row.key).toLowerCase()}`;
          btn.addEventListener("click", () => {
            this._setPath(row.path, this._defaultNested(row.schema));
            this._render();
            this._emitChange(true);
          });
          el.appendChild(btn);
          grid.appendChild(el);
          continue;
        }

        if (row.optional) {
          const el = document.createElement("div");
          el.className = "form-field";
          el.innerHTML = `<label>${labelFor(row.key)}</label>`;
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn-inline";
          btn.textContent = "Set";
          btn.addEventListener("click", () => {
            const ps = this.resolver.resolve(row.schema);
            const def = ps.default ?? (ps.type === "number" ? 0 : "");
            this._setPath(row.path, def);
            this._render();
            this._emitChange(true);
          });
          el.appendChild(btn);
          grid.appendChild(el);
          continue;
        }

        grid.appendChild(this._formField(row.path, row.key, row.value, row.schema));
      }
      return grid;
    }

    _formField(path, key, value, schema) {
      const field = document.createElement("div");
      field.className = "form-field";
      field.dataset.configPath = path.join(".");

      const label = document.createElement("label");
      label.textContent = labelFor(key);
      field.appendChild(label);
      const inp = this._input(path, key, value, schema);
      if (inp.dataset) inp.dataset.configPath = path.join(".");
      field.appendChild(inp);
      if (key === "correlation") {
        const hint = document.createElement("p");
        hint.className = "form-hint correlation-hint";
        const updateHint = () => {
          const v = inp.value || value;
          hint.textContent = CORRELATION_HINTS[v] || "";
        };
        updateHint();
        inp.addEventListener("change", updateHint);
        field.appendChild(hint);
      }
      return field;
    }

    _renderCombustion(value, schema) {
      const section = this._configSection(
        "Combustion model",
        "Backend selection and optional CEA table data."
      ).el;
      const body = section.querySelector(".config-section-body");
      const grid = document.createElement("div");
      grid.className = "form-grid";

      const backendSchema = this.resolver.resolve(schema.properties?.backend || {});
      grid.appendChild(this._formField(["combustion", "backend"], "backend", value.backend, backendSchema));

      if (value.backend === "table" && value.table?.of) {
        const note = document.createElement("p");
        note.className = "form-hint form-field-wide";
        note.textContent = `CEA table — ${value.table.of.length} O/F points (edit JSON to change)`;
        grid.appendChild(note);

        const ta = document.createElement("textarea");
        ta.className = "editor-json form-field-wide";
        ta.rows = 8;
        ta.value = JSON.stringify(value.table, null, 2);
        ta.addEventListener("input", () => {
          if (!this.editable) return;
          this.onDirty(true);
        });
        ta.addEventListener("change", () => {
          try {
            this._setPath(["combustion", "table"], JSON.parse(ta.value));
            ta.classList.remove("error");
          } catch {
            ta.classList.add("error");
          }
        });
        const field = document.createElement("div");
        field.className = "form-field form-field-wide";
        field.appendChild(ta);
        grid.appendChild(field);
      } else if (value.backend === "rocketcea") {
        const hint = document.createElement("p");
        hint.className = "form-hint form-field-wide";
        hint.textContent = "RocketCEA backend — properties computed at runtime.";
        grid.appendChild(hint);
      }
      body.appendChild(grid);
      return section;
    }

    _defaultNested(schema) {
      const resolved = this.resolver.resolve(schema);
      const out = {};
      for (const [k, raw] of Object.entries(resolved.properties || {})) {
        const ps = this.resolver.resolve(raw);
        if (ps.default !== undefined) out[k] = ps.default;
        else if (ps.type === "number" || ps.type === "integer") out[k] = 0;
        else if (ps.type === "array" && ps.minItems === 2) out[k] = [0, 0];
      }
      return out;
    }

    _input(path, key, value, schema) {
      const resolved = this.resolver.resolve(schema);

      const literals = resolved.enum || this._stringLiterals(key);
      if (literals) {
        const sel = document.createElement("select");
        for (const v of literals) {
          const opt = document.createElement("option");
          opt.value = v;
          opt.textContent = v;
          sel.appendChild(opt);
        }
        sel.value = value ?? resolved.default ?? literals[0];
        sel.addEventListener("change", () => this._setPath(path, sel.value));
        return sel;
      }

      if (resolved.type === "array" && resolved.minItems === 2 && resolved.maxItems === 2) {
        return this._tupleInput(path, value);
      }

      if (resolved.type === "boolean") {
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = !!value;
        cb.addEventListener("change", () => this._setPath(path, cb.checked));
        return cb;
      }

      if (resolved.type === "integer" || resolved.type === "number") {
        const inp = document.createElement("input");
        inp.type = "number";
        inp.step = resolved.type === "integer" ? "1" : "any";
        if (resolved.minimum != null) inp.min = resolved.minimum;
        if (resolved.maximum != null) inp.max = resolved.maximum;
        inp.value = value ?? resolved.default ?? "";
        const isOptional = resolved.nullable || false;
        const apply = () => {
          if (inp.value === "") {
            if (isOptional) this._setPath(path, null);
            return;
          }
          const v = resolved.type === "integer"
            ? parseInt(inp.value, 10) : parseFloat(inp.value);
          if (Number.isNaN(v)) return;
          this._setPath(path, v);
        };
        inp.addEventListener("input", apply);
        inp.addEventListener("change", () => this._notifyChange(true));
        return inp;
      }

      const inp = document.createElement("input");
      inp.type = "text";
      inp.value = value ?? resolved.default ?? "";
      inp.addEventListener("input", () => this._setPath(path, inp.value));
      return inp;
    }

    _tupleInput(path, value) {
      const wrap = document.createElement("div");
      wrap.className = "tuple-row";
      const arr = Array.isArray(value) ? value : [0, 0];
      [0, 1].forEach((i) => {
        const inp = document.createElement("input");
        inp.type = "number";
        inp.step = "any";
        inp.value = arr[i] ?? "";
        inp.addEventListener("input", () => {
          const next = [...(this._getPath(path) || [0, 0])];
          next[i] = parseFloat(inp.value);
          this._setPath(path, next);
        });
        wrap.appendChild(inp);
      });
      return wrap;
    }

    _stringLiterals(key) {
      const map = {
        contour: ["rao_bell", "conical", "moc"],
        correlation: ["gnielinski", "chen", "jackson"],
        backend: ["rocketcea", "table"],
      };
      return map[key] || null;
    }
  }

  window.ConfigEditor = ConfigEditor;
})();
