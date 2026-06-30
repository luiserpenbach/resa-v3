/**
 * Unified Regen Cooling design UI — circuit definition, profile editors, toggles.
 */
(function () {
  const PARAM_SPECS = {
    height: {
      id: "height",
      plotKey: "height_m",
      label: "Channel height",
      unit: "m",
      displayUnit: "mm",
      scale: 1000,
      path: ["regen", "channels", "height"],
      defaultVal: 0.0035,
    },
    rib: {
      id: "rib",
      plotKey: "rib_width_m",
      label: "Rib width",
      unit: "m",
      displayUnit: "mm",
      scale: 1000,
      path: ["regen", "channels", "rib", "width"],
      ribModePath: ["regen", "channels", "rib", "mode"],
      defaultVal: 0.0008,
    },
    wall: {
      id: "wall",
      plotKey: "wall_thickness_m",
      label: "Inner wall thickness",
      unit: "m",
      displayUnit: "mm",
      scale: 1000,
      path: ["regen", "channels", "inner_wall_thickness"],
      defaultVal: 0.0008,
    },
    helix: {
      id: "helix",
      plotKey: "beta_deg",
      label: "Helix angle β",
      unit: "deg",
      displayUnit: "°",
      scale: 1,
      path: ["regen", "channels", "helix", "profile"],
      defaultVal: 0,
    },
  };

  const AXIAL_STEP_M = 0.0001;
  const ANGLE_STEP_DEG = 0.1;

  function quantizeCoord(v, isAngle = false) {
    if (v == null || Number.isNaN(v)) return v;
    const step = isAngle ? ANGLE_STEP_DEG : AXIAL_STEP_M;
    return Math.round(v / step) * step;
  }

  function formatCoord(v, isAngle = false) {
    if (v == null || Number.isNaN(v)) return "";
    return quantizeCoord(v, isAngle).toFixed(isAngle ? 1 : 4);
  }

  function getAxialBounds(editor, sectionData) {
    const sd = sectionData || editor.workspace?.sectionData;
    if (sd?.x_range) {
      const [a, b] = sd.x_range;
      return [Math.min(a, b), Math.max(a, b)];
    }
    const xs = sd?.profiles?.x_m;
    if (Array.isArray(xs) && xs.length) {
      return [Math.min(...xs), Math.max(...xs)];
    }
    const ch = editor.config?.regen?.channels || {};
    const start = ch.start_x;
    const stop = ch.stop_x;
    if (start != null && stop != null) {
      return [Math.min(start, stop), Math.max(start, stop)];
    }
    if (start != null) return [start, stop ?? Math.max(start + 0.05, 0.15)];
    if (stop != null) return [start ?? Math.min(stop - 0.05, -0.15), stop];
    return [-0.15, 0.15];
  }

  function defaultBreakpointPair(editor, value, sectionData) {
    const [x0, x1] = getAxialBounds(editor, sectionData);
    const v = value ?? 0;
    return [[x0, v], [x1, v]];
  }

  function getPath(obj, path) {
    let cur = obj;
    for (const k of path) cur = cur?.[k];
    return cur;
  }

  function isScalar(val) {
    return typeof val === "number" || val == null;
  }

  function toBreakpoints(val, defaultVal, editor, sectionData) {
    if (isScalar(val)) {
      const v = val ?? defaultVal;
      if (editor) return defaultBreakpointPair(editor, v, sectionData);
      return [[-0.15, v], [0.15, v]];
    }
    if (Array.isArray(val) && val.length && Array.isArray(val[0])) {
      return val.map((p) => [p[0], p[1]]);
    }
    if (editor) return defaultBreakpointPair(editor, defaultVal, sectionData);
    return [[-0.15, defaultVal], [0.15, defaultVal]];
  }

  function fromBreakpoints(pts, asScalar, spec) {
    const isAngle = spec?.unit === "deg";
    const clean = pts
      .map((p) => [
        quantizeCoord(parseFloat(p[0]), false),
        quantizeCoord(parseFloat(p[1]), isAngle),
      ])
      .filter((p) => !Number.isNaN(p[0]) && !Number.isNaN(p[1]));
    if (!clean.length) return 0;
    clean.sort((a, b) => a[0] - b[0]);
    if (asScalar) return clean[0][1];
    return clean;
  }

  function fmtVal(v, spec) {
    if (v == null || Number.isNaN(v)) return "—";
    if (spec.scale === 1) return `${v.toFixed(1)}${spec.displayUnit}`;
    return `${(v * spec.scale).toFixed(2)} ${spec.displayUnit}`;
  }

  function isConstant(editor, specId) {
    const spec = PARAM_SPECS[specId];
    if (!spec) return true;
    if (specId === "rib") {
      const mode = editor._getPath(spec.ribModePath);
      if (mode === "variable") return false;
      return isScalar(editor._getPath(spec.path));
    }
    const val = editor._getPath(spec.path);
    return isScalar(val);
  }

  function getBreakpoints(editor, specId, sectionData) {
    const spec = PARAM_SPECS[specId];
    return toBreakpoints(editor._getPath(spec.path), spec.defaultVal, editor, sectionData);
  }

  function setBreakpoints(editor, specId, pts, { notify = true } = {}) {
    const spec = PARAM_SPECS[specId];
    if (specId === "rib") {
      editor._setPath(spec.ribModePath, "variable", { notify: false });
    }
    editor._setPath(spec.path, fromBreakpoints(pts, false, spec), { notify });
  }

  function setConstant(editor, specId, value, { notify = true } = {}) {
    const spec = PARAM_SPECS[specId];
    if (specId === "rib") {
      editor._setPath(spec.ribModePath, "fixed_width", { notify: false });
    }
    editor._setPath(spec.path, value ?? spec.defaultVal, { notify });
  }

  function setConstantFromCurrent(editor, specId) {
    const spec = PARAM_SPECS[specId];
    if (specId === "helix") {
      setConstant(editor, specId, 0, { notify: true });
      return;
    }
    const pts = getBreakpoints(editor, specId);
    const v = pts[0]?.[1] ?? spec.defaultVal;
    setConstant(editor, specId, v, { notify: true });
  }

  function setVariableFromCurrent(editor, specId) {
    const spec = PARAM_SPECS[specId];
    const val = editor._getPath(spec.path);
    const [x0, x1] = getAxialBounds(editor);
    let pts = toBreakpoints(val, spec.defaultVal, editor);
    if (specId === "helix") {
      const v = isScalar(val) ? (val ?? 0) : (pts[0]?.[1] ?? 0);
      if (v === 0 && pts.every((p) => p[1] === 0)) {
        const xMid = quantizeCoord(Math.max(x0, Math.min(x1, 0)), false);
        pts = [[x0, 0], [xMid, 15], [x1, 15]];
      }
    }
    setBreakpoints(editor, specId, pts, { notify: true });
  }

  /** Canvas plot + linked breakpoint table with +/- station controls. */
  class AxialProfileEditor {
    constructor(container, editor, specId, workspace) {
      this.container = container;
      this.editor = editor;
      this.specId = specId;
      this.spec = PARAM_SPECS[specId];
      this.workspace = workspace;
      this.selectedIdx = 0;
      this.sectionData = null;
      this._build();
    }

    _build() {
      this.container.innerHTML = "";
      this.container.className = "axial-profile-editor";

      const head = document.createElement("div");
      head.className = "axial-profile-head";
      head.innerHTML = `<span class="axial-profile-title">${this.spec.label}</span>`;
      this.stationLbl = document.createElement("span");
      this.stationLbl.className = "axial-profile-stations";
      head.appendChild(this.stationLbl);

      const tools = document.createElement("div");
      tools.className = "axial-profile-tools";
      this.btnAdd = document.createElement("button");
      this.btnAdd.type = "button";
      this.btnAdd.className = "btn-icon axial-btn-add";
      this.btnAdd.title = "Add station";
      this.btnAdd.textContent = "+";
      this.btnRem = document.createElement("button");
      this.btnRem.type = "button";
      this.btnRem.className = "btn-icon axial-btn-rem";
      this.btnRem.title = "Remove selected station";
      this.btnRem.textContent = "−";
      tools.appendChild(this.btnAdd);
      tools.appendChild(this.btnRem);
      head.appendChild(tools);
      this.container.appendChild(head);

      const plotWrap = document.createElement("div");
      plotWrap.className = "axial-profile-plot-wrap";
      this.canvas = document.createElement("canvas");
      this.canvas.className = "axial-profile-canvas";
      plotWrap.appendChild(this.canvas);
      this.container.appendChild(plotWrap);

      const tableWrap = document.createElement("div");
      tableWrap.className = "axial-profile-table-wrap";
      this.table = document.createElement("table");
      this.table.className = "axial-profile-table";
      this.table.innerHTML = `<thead><tr><th>x (m)</th><th>value (${this.spec.unit})</th></tr></thead><tbody></tbody>`;
      tableWrap.appendChild(this.table);
      this.container.appendChild(tableWrap);

      this.btnAdd.addEventListener("click", () => this._addStation());
      this.btnRem.addEventListener("click", () => this._removeStation());
      this._setupPlotInteraction();
      this._resizeObs = new ResizeObserver(() => this.draw());
      this._resizeObs.observe(this.container);

      this.syncFromConfig();
    }

    syncFromConfig() {
      if (this._dragIdx != null) return;
      this.pts = getBreakpoints(this.editor, this.specId, this.sectionData).map((p) => [
        quantizeCoord(p[0], false),
        quantizeCoord(p[1], this.spec.unit === "deg"),
      ]);
      this.selectedIdx = Math.min(this.selectedIdx, Math.max(0, this.pts.length - 1));
      this._renderTable();
      this.draw();
    }

    setSectionData(data) {
      this.sectionData = data;
      this.draw();
    }

    _isAngle() {
      return this.spec.unit === "deg";
    }

    _valueStep() {
      return this._isAngle() ? String(ANGLE_STEP_DEG) : String(AXIAL_STEP_M);
    }

    _axialBounds() {
      return getAxialBounds(this.editor, this.sectionData);
    }

    _clampX(x) {
      const [xMin, xMax] = this._axialBounds();
      return Math.min(xMax, Math.max(xMin, quantizeCoord(x, false)));
    }

    _quantizePoint(x, y) {
      return [
        this._clampX(x),
        quantizeCoord(y, this._isAngle()),
      ];
    }

    _selectRow(idx, { scroll = false } = {}) {
      if (idx < 0 || idx >= this.pts.length) return;
      this.selectedIdx = idx;
      this._updateRowHighlight();
      this.draw();
      if (scroll) {
        const tr = this.table.querySelectorAll("tbody tr")[idx];
        tr?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    }

    _canvasColors() {
      const s = getComputedStyle(document.documentElement);
      return {
        accent: s.getPropertyValue("--accent").trim() || "#4a9eff",
        warning: s.getPropertyValue("--warning").trim() || "#f0a030",
        markerStroke: s.getPropertyValue("--axial-marker-stroke").trim() || "#ffffff",
        plotBg: s.getPropertyValue("--plot-bg").trim() || "#0f1014",
        textMuted: s.getPropertyValue("--text-muted").trim() || "#888",
      };
    }

    _renderTable() {
      const tbody = this.table.querySelector("tbody");
      tbody.innerHTML = "";
      const isAngle = this._isAngle();
      this.pts.forEach((pt, idx) => {
        const tr = document.createElement("tr");
        tr.className = idx === this.selectedIdx ? "selected" : "";
        tr.innerHTML = `
          <td><input type="number" class="bp-x" step="${AXIAL_STEP_M}" value="${formatCoord(pt[0], false)}"></td>
          <td><input type="number" class="bp-v" step="${this._valueStep()}" value="${formatCoord(pt[1], isAngle)}"></td>
        `;
        tr.addEventListener("focusin", () => this._selectRow(idx));
        const xInp = tr.querySelector(".bp-x");
        const vInp = tr.querySelector(".bp-v");
        xInp.addEventListener("input", (e) => {
          const v = parseFloat(e.target.value);
          if (Number.isNaN(v)) return;
          this.pts[idx][0] = v;
          setBreakpoints(this.editor, this.specId, this.pts, { notify: false });
          this.draw();
        });
        vInp.addEventListener("input", (e) => {
          const v = parseFloat(e.target.value);
          if (Number.isNaN(v)) return;
          this.pts[idx][1] = v;
          setBreakpoints(this.editor, this.specId, this.pts, { notify: false });
          this.draw();
        });
        xInp.addEventListener("change", () => this._finalizeEdit());
        vInp.addEventListener("change", () => this._finalizeEdit());
        tbody.appendChild(tr);
      });
      this.stationLbl.textContent = `${this.pts.length} station${this.pts.length === 1 ? "" : "s"}`;
      this.btnRem.disabled = this.pts.length <= 2 || !this.editor.editable;
    }

    _updateRowHighlight() {
      this.table.querySelectorAll("tbody tr").forEach((tr, idx) => {
        tr.classList.toggle("selected", idx === this.selectedIdx);
      });
    }

    _syncTableInputs() {
      const isAngle = this._isAngle();
      this.table.querySelectorAll("tbody tr").forEach((tr, idx) => {
        const pt = this.pts[idx];
        if (!pt) return;
        const xInp = tr.querySelector(".bp-x");
        const vInp = tr.querySelector(".bp-v");
        if (xInp && document.activeElement !== xInp) xInp.value = formatCoord(pt[0], false);
        if (vInp && document.activeElement !== vInp) vInp.value = formatCoord(pt[1], isAngle);
      });
    }

    _finalizeEdit() {
      const activePt = this.pts[this.selectedIdx];
      this.pts = this.pts.map(([x, y]) => this._quantizePoint(x, y));
      this.pts.sort((a, b) => a[0] - b[0]);
      if (activePt) {
        const qx = quantizeCoord(activePt[0], false);
        const qy = quantizeCoord(activePt[1], this._isAngle());
        this.selectedIdx = this.pts.findIndex(
          (p) => Math.abs(p[0] - qx) < AXIAL_STEP_M * 0.5
            && Math.abs(p[1] - qy) < (this._isAngle() ? ANGLE_STEP_DEG : AXIAL_STEP_M) * 0.5
        );
        if (this.selectedIdx < 0) this.selectedIdx = 0;
      }
      setBreakpoints(this.editor, this.specId, this.pts, { notify: false });
      this.editor.onDirty?.(true);
      this.workspace?._debouncedCooling?.();
      this._renderTable();
      this.draw();
      this.editor._notifyChange(true);
    }

    _commit(refresh) {
      this.pts.sort((a, b) => a[0] - b[0]);
      setBreakpoints(this.editor, this.specId, this.pts, { notify: false });
      if (refresh) {
        this.editor.onDirty?.(true);
        this.workspace?._debouncedCooling?.();
      }
      this._renderTable();
      this.draw();
    }

    _addStation() {
      if (!this.editor.editable) return;
      const [boundMin, boundMax] = this._axialBounds();
      let newX;
      if (this.selectedIdx >= 0 && this.pts[this.selectedIdx]) {
        const sel = this.pts[this.selectedIdx][0];
        const next = this.pts[this.selectedIdx + 1];
        if (next) {
          newX = (sel + next[0]) / 2;
        } else if (this.pts[this.selectedIdx - 1]) {
          const prev = this.pts[this.selectedIdx - 1][0];
          newX = sel + Math.min((boundMax - sel) * 0.5, Math.max(AXIAL_STEP_M, (sel - prev) * 0.5));
        } else {
          newX = (boundMin + boundMax) / 2;
        }
      } else {
        newX = (boundMin + boundMax) / 2;
      }
      newX = this._clampX(newX);
      const interpY = quantizeCoord(this._interpAt(newX), this._isAngle());
      this.pts.push([newX, interpY]);
      this.pts.sort((a, b) => a[0] - b[0]);
      this.selectedIdx = this.pts.findIndex(
        (p) => Math.abs(p[0] - newX) < AXIAL_STEP_M * 0.5
      );
      if (this.selectedIdx < 0) this.selectedIdx = 0;
      this._commit(true);
      this.editor._notifyChange(true);
    }

    _removeStation() {
      if (!this.editor.editable || this.pts.length <= 2) return;
      this.pts.splice(this.selectedIdx, 1);
      this.selectedIdx = Math.min(this.selectedIdx, this.pts.length - 1);
      this._commit(true);
      this.editor._notifyChange(true);
    }

    _interpAt(x) {
      const pts = this.pts;
      if (!pts.length) return this.spec.defaultVal;
      if (x <= pts[0][0]) return pts[0][1];
      if (x >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
      for (let i = 0; i < pts.length - 1; i++) {
        if (x >= pts[i][0] && x <= pts[i + 1][0]) {
          const t = (x - pts[i][0]) / (pts[i + 1][0] - pts[i][0] || 1);
          return pts[i][1] + t * (pts[i + 1][1] - pts[i][1]);
        }
      }
      return pts[0][1];
    }

    _pickPlot(e) {
      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const m = this._plotMetrics();
      const frac = (mx - m.pad) / m.plotW;
      const xm = m.xMin + frac * (m.xMax - m.xMin);
      let best = 0;
      let bestD = Infinity;
      this.pts.forEach((p, i) => {
        const d = Math.abs(p[0] - xm);
        if (d < bestD) { bestD = d; best = i; }
      });
      this.selectedIdx = best;
      this._selectRow(best, { scroll: true });
    }

    _plotMetrics() {
      const rect = this.container.querySelector(".axial-profile-plot-wrap")?.getBoundingClientRect()
        || { width: 400 };
      const w = Math.max(rect.width - 4, 200);
      const h = 160;
      const pad = 40;
      const plotW = w - pad * 2;
      const plotH = h - pad * 2;
      const [xMin, xMax] = this._xRange();

      let curveY = this.pts.map((p) => p[1]);
      if (this.sectionData?.profiles?.[this.spec.plotKey]) {
        curveY = this.sectionData.profiles[this.spec.plotKey];
      }
      const yMax = Math.max(...curveY, ...this.pts.map((p) => p[1]), this.spec.defaultVal, 0.001) * 1.2;
      const yMin = 0;

      return { w, h, pad, plotW, plotH, xMin, xMax, yMin, yMax };
    }

    _toPlot(x, y, m) {
      return {
        px: m.pad + ((x - m.xMin) / (m.xMax - m.xMin || 1)) * m.plotW,
        py: m.pad + m.plotH - ((y - m.yMin) / (m.yMax - m.yMin || 1)) * m.plotH,
      };
    }

    _fromPlot(px, py, m) {
      const x = m.xMin + ((px - m.pad) / m.plotW) * (m.xMax - m.xMin);
      const y = m.yMin + (1 - (py - m.pad) / m.plotH) * (m.yMax - m.yMin);
      return this._quantizePoint(x, y);
    }

    _hitTestPoint(e, radius = 10) {
      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const m = this._plotMetrics();
      let best = null;
      let bestD = Infinity;
      this.pts.forEach((p, i) => {
        const { px, py } = this._toPlot(p[0], p[1], m);
        const d = Math.hypot(mx - px, my - py);
        if (d <= radius && d < bestD) {
          bestD = d;
          best = i;
        }
      });
      return best;
    }

    _setupPlotInteraction() {
      this._dragIdx = null;
      this._onPlotMove = (e) => {
        if (this._dragIdx == null) return;
        const rect = this.canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const m = this._plotMetrics();
        const [x, y] = this._fromPlot(mx, my, m);
        this.pts[this._dragIdx][0] = x;
        this.pts[this._dragIdx][1] = y;
        setBreakpoints(this.editor, this.specId, this.pts, { notify: false });
        this._syncTableInputs();
        this.draw();
      };
      this._onPlotUp = () => {
        if (this._dragIdx == null) return;
        this.selectedIdx = this._dragIdx;
        this._dragIdx = null;
        this.canvas.style.cursor = this.editor.editable ? "crosshair" : "";
        this._finalizeEdit();
      };
      this.canvas.addEventListener("mousedown", (e) => {
        if (!this.editor.editable) return;
        const hit = this._hitTestPoint(e);
        if (hit != null) {
          e.preventDefault();
          this._dragIdx = hit;
          this._selectRow(hit);
          this.canvas.style.cursor = "grabbing";
          return;
        }
        this._pickPlot(e);
      });
      window.addEventListener("mousemove", this._onPlotMove);
      window.addEventListener("mouseup", this._onPlotUp);
      if (this.editor.editable) this.canvas.style.cursor = "crosshair";
    }

    _xRange() {
      const [boundMin, boundMax] = this._axialBounds();
      if (this.sectionData?.x_range) return [boundMin, boundMax];
      const xs = this.pts.map((p) => p[0]);
      const ptMin = xs.length ? Math.min(...xs) : boundMin;
      const ptMax = xs.length ? Math.max(...xs) : boundMax;
      return [
        Math.min(boundMin, ptMin),
        Math.max(boundMax, ptMax),
      ];
    }

    draw() {
      const ctx = this.canvas.getContext("2d");
      const colors = this._canvasColors();
      const dpr = window.devicePixelRatio || 1;
      const m = this._plotMetrics();
      const { w, h, pad, plotW, plotH, xMin, xMax, yMin, yMax } = m;
      this.canvas.width = w * dpr;
      this.canvas.height = h * dpr;
      this.canvas.style.width = `${w}px`;
      this.canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = colors.plotBg;
      ctx.fillRect(0, 0, w, h);

      const toX = (x) => pad + ((x - xMin) / (xMax - xMin || 1)) * plotW;
      const toY = (y) => pad + plotH - ((y - yMin) / (yMax - yMin || 1)) * plotH;

      let curveX = this.pts.map((p) => p[0]);
      let curveY = this.pts.map((p) => p[1]);
      if (this.sectionData?.profiles?.[this.spec.plotKey]) {
        curveX = this.sectionData.profiles.x_m;
        curveY = this.sectionData.profiles[this.spec.plotKey];
      }

      if (this.sectionData?.contour) {
        const crs = this.sectionData.contour.r_m;
        const xs = this.sectionData.profiles?.x_m || curveX;
        const rMax = Math.max(...crs);
        ctx.fillStyle = "rgba(100,120,160,0.1)";
        ctx.beginPath();
        for (let i = 0; i < xs.length; i++) {
          const xi = toX(xs[i]);
          const ri = (crs[Math.min(i, crs.length - 1)] / rMax) * plotH * 0.3;
          if (i === 0) ctx.moveTo(xi, pad + plotH);
          ctx.lineTo(xi, pad + plotH - ri);
        }
        ctx.lineTo(toX(xs[xs.length - 1]), pad + plotH);
        ctx.closePath();
        ctx.fill();
      }

      ctx.strokeStyle = colors.accent;
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < curveX.length; i++) {
        const px = toX(curveX[i]);
        const py = toY(curveY[i]);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();

      this.pts.forEach((p, idx) => {
        const px = toX(p[0]);
        const py = toY(p[1]);
        const selected = idx === this.selectedIdx;
        const r = selected ? 7 : 5;
        ctx.beginPath();
        ctx.arc(px, py, r, 0, Math.PI * 2);
        ctx.fillStyle = selected ? colors.warning : colors.accent;
        ctx.fill();
        ctx.strokeStyle = colors.markerStroke;
        ctx.lineWidth = selected ? 2 : 1.5;
        ctx.stroke();
      });

      ctx.fillStyle = colors.textMuted;
      ctx.font = "10px system-ui,sans-serif";
      ctx.fillText(this.spec.label, pad, 12);
      ctx.textAlign = "right";
      ctx.fillText(fmtVal(this.pts[this.selectedIdx]?.[1], this.spec), w - pad, 12);
      ctx.textAlign = "left";
    }
  }

  function addSection(parent, title, hint) {
    const sec = document.createElement("section");
    sec.className = "config-section regen-design-section form-section";
    const h = document.createElement("h3");
    h.className = "form-section-title";
    h.textContent = title;
    sec.appendChild(h);
    if (hint) {
      const p = document.createElement("p");
      p.className = "form-section-hint";
      p.textContent = hint;
      sec.appendChild(p);
    }
    const body = document.createElement("div");
    body.className = "config-section-body regen-design-section-body";
    sec.appendChild(body);
    parent.appendChild(sec);
    return body;
  }

  function addNumField(grid, editor, label, path, val, opts = {}) {
    const field = document.createElement("div");
    field.className = "form-field";
    field.dataset.configPath = path.join(".");
    field.innerHTML = `<label>${label}</label>`;
    const inp = document.createElement("input");
    inp.type = "number";
    inp.step = opts.step || "any";
    inp.value = val ?? "";
    inp.placeholder = opts.placeholder || "";
    if (opts.min != null) inp.min = opts.min;
    if (opts.max != null) inp.max = opts.max;
    inp.addEventListener("input", () => {
      if (inp.value === "") {
        if (path[path.length - 1] === "start_x" || path[path.length - 1] === "stop_x") {
          editor._setPath(path, null);
        }
        return;
      }
      const v = parseFloat(inp.value);
      if (Number.isNaN(v)) return;
      editor._setPath(path, v);
    });
    inp.addEventListener("change", () => editor._notifyChange(true));
    field.appendChild(inp);
    if (opts.hint) {
      const h = document.createElement("span");
      h.className = "field-unit-hint";
      h.textContent = opts.hint;
      field.appendChild(h);
    }
    grid.appendChild(field);
  }

  function addSelectField(grid, editor, label, path, options, val) {
    const field = document.createElement("div");
    field.className = "form-field";
    field.innerHTML = `<label>${label}</label>`;
    const sel = document.createElement("select");
    for (const [v, t] of options) {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = t;
      sel.appendChild(o);
    }
    sel.value = val ?? options[0][0];
    sel.addEventListener("change", () => {
      editor._setPath(path, sel.value, { notify: true });
    });
    field.appendChild(sel);
    grid.appendChild(field);
  }

  function addToggleField(grid, editor, label, path, checked) {
    const field = document.createElement("div");
    field.className = "form-field form-field-wide";
    const lbl = document.createElement("label");
    lbl.className = "toggle-inline";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = checked;
    cb.addEventListener("change", () => {
      editor._setPath(path, cb.checked, { notify: true });
    });
    lbl.appendChild(cb);
    lbl.appendChild(document.createTextNode(` ${label}`));
    field.appendChild(lbl);
    grid.appendChild(field);
  }

  function buildEnableRegenBlock(editor) {
    const cool = editor.config.cooling || {};
    const card = document.createElement("section");
    card.className = "config-section regen-design-section form-section regen-enable-card";
    card.innerHTML = `
      <h3 class="form-section-title">Regen cooling circuit</h3>
      <p class="form-section-hint">Enable axial regen channel layout for partial or full-chamber coverage. Multiple circuits per engine are planned — start with circuit 1.</p>
    `;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-inline btn-primary";
    btn.textContent = "Enable regen cooling circuit";
    btn.addEventListener("click", () => {
      editor.config.regen = {
        meta: { name: `${editor.config.engine || "engine"}_regen`, description: "Circuit 1", version: "0.1" },
        contour: { type: "from_engine" },
        sync: {
          contour: true, hot_gas_pc_bar: true, hot_gas_tc_K: true, hot_gas_gamma: true,
          hot_gas_mol_mass_kg_kmol: true, hot_gas_c_star_m_s: true, hot_gas_bartz_correction: true,
          of_ratio: true, mdot: true,
        },
        channels: {
          count: cool.n_channels || 72,
          start_x: null,
          stop_x: null,
          inner_wall_thickness: cool.inner_wall_thickness_m || 0.0008,
          height: cool.channel_height_m || 0.0035,
          rib: { mode: "fixed_width", width: cool.rib_width_m || 0.0008 },
          helix: { profile: 0, interp: "pchip", handedness: "right" },
          min_channel_width: 0.0008,
        },
        geometry: { n_stations: 300, width_reference: "mid_height" },
        solver: {
          enabled: true,
          coolant: cool.coolant || "Hydrogen",
          coolant_side: "fuel",
          mdot_from_engine: true,
          inlet: {
            pressure_bar: cool.inlet_p_bar || 60,
            temperature_K: cool.inlet_T_K || 90,
            location: "nozzle_end",
          },
          wall: { material: cool.wall_material || "Inconel 718", max_wall_temp_K: 1200 },
        },
        export: { stl: true, step: false },
      };
      editor._render();
      editor._emitChange(true);
    });
    card.appendChild(btn);
    return card;
  }

  function buildCircuitSection(editor) {
    const regen = editor.config.regen;
    const ch = regen.channels || {};
    const body = addSection(
      editor._regenFormRoot,
      "1 · Regen circuit",
      "Define channel count and axial extent on the chamber contour (x = 0 at throat; chamber x < 0, nozzle x > 0). Leave start/stop blank for full coverage."
    );
    const grid = document.createElement("div");
    grid.className = "form-grid";
    body.appendChild(grid);

    const nameField = document.createElement("div");
    nameField.className = "form-field form-field-wide";
    nameField.innerHTML = "<label>Circuit name</label>";
    const nameInp = document.createElement("input");
    nameInp.type = "text";
    nameInp.value = regen.meta?.name || "Circuit 1";
    nameInp.addEventListener("input", () => {
      if (!editor.config.regen.meta) editor.config.regen.meta = {};
      editor.config.regen.meta.name = nameInp.value;
    });
    nameInp.addEventListener("change", () => editor._notifyChange(true));
    nameField.appendChild(nameInp);
    grid.appendChild(nameField);

    addNumField(grid, editor, "Channel count", ["regen", "channels", "count"], ch.count, { step: "1" });
    const countInp = grid.querySelector('[data-config-path="regen.channels.count"] input')
      || grid.lastElementChild?.querySelector("input");
    if (countInp) {
      countInp.addEventListener("change", () => {
        const v = parseInt(countInp.value, 10);
        if (!Number.isNaN(v)) editor._setPath(["cooling", "n_channels"], v, { notify: false });
      });
    }
    addNumField(grid, editor, "Start x (m)", ["regen", "channels", "start_x"], ch.start_x, {
      placeholder: "injector (auto)",
    });
    addNumField(grid, editor, "Stop x (m)", ["regen", "channels", "stop_x"], ch.stop_x, {
      placeholder: "nozzle exit (auto)",
    });
    addNumField(grid, editor, "Min channel width (m)", ["regen", "channels", "min_channel_width"], ch.min_channel_width);

    const geom = regen.geometry || {};
    addNumField(grid, editor, "Layout stations", ["regen", "geometry", "n_stations"], geom.n_stations, { step: "1" });
    addSelectField(grid, editor, "Width reference", ["regen", "geometry", "width_reference"],
      [["mid_height", "Mid height"], ["floor", "Floor"]], geom.width_reference);
  }

  function buildCoolantSection(editor) {
    const regen = editor.config.regen;
    const sol = regen.solver || {};
    const cool = editor.config.cooling || {};
    const body = addSection(
      editor._regenFormRoot,
      "2 · Coolant & mass flow",
      "Coolant species, inlet conditions, and fraction of engine propellant flow routed through channels."
    );
    const grid = document.createElement("div");
    grid.className = "form-grid";
    body.appendChild(grid);

    addToggleField(grid, editor, "Run regen thermal solver", ["regen", "solver", "enabled"], sol.enabled !== false);

    const coolField = document.createElement("div");
    coolField.className = "form-field";
    coolField.innerHTML = "<label>Coolant species</label>";
    const coolInp = document.createElement("input");
    coolInp.type = "text";
    coolInp.value = sol.coolant || cool.coolant || "";
    coolInp.addEventListener("input", () => editor._setPath(["regen", "solver", "coolant"], coolInp.value));
    coolInp.addEventListener("change", () => editor._notifyChange(true));
    coolField.appendChild(coolInp);
    grid.appendChild(coolField);

    addSelectField(grid, editor, "Coolant side", ["regen", "solver", "coolant_side"],
      [["fuel", "Fuel"], ["oxidizer", "Oxidizer"]], sol.coolant_side || "fuel");
    addNumField(grid, editor, "Coolant mass fraction", ["regen", "solver", "coolant_fraction"], sol.coolant_fraction, {
      placeholder: "auto from O/F", min: 0, max: 1,
    });
    addNumField(grid, editor, "Inlet pressure (bar)", ["regen", "solver", "inlet", "pressure_bar"], sol.inlet?.pressure_bar);
    addNumField(grid, editor, "Inlet temperature (K)", ["regen", "solver", "inlet", "temperature_K"], sol.inlet?.temperature_K);
    addSelectField(grid, editor, "Inlet location", ["regen", "solver", "inlet", "location"],
      [["nozzle_end", "Nozzle end"], ["injector_end", "Injector end"]], sol.inlet?.location || "nozzle_end");
  }

  function buildWallSection(editor) {
    const regen = editor.config.regen;
    const sol = regen.solver || {};
    const cool = editor.config.cooling || {};
    const ch = editor.config.chamber || {};
    const body = addSection(
      editor._regenFormRoot,
      "3 · Wall & heat transfer",
      "Wall material limits, tube-side correlation, and hot-gas discretization."
    );
    const grid = document.createElement("div");
    grid.className = "form-grid";
    body.appendChild(grid);

    addNumField(grid, editor, "Max wall temperature (K)", ["regen", "solver", "wall", "max_wall_temp_K"], sol.wall?.max_wall_temp_K, { step: "1" });
    addToggleField(grid, editor, "Helix curvature enhancement", ["regen", "solver", "curvature_enhancement"],
      sol.curvature_enhancement !== false);

    const chSchema = editor.resolver?.propSchema(editor.schema, "chamber");
    if (chSchema) {
      for (const k of ["bartz_correction", "n_stations"]) {
        const ps = editor.resolver.propSchema(chSchema, k);
        if (ps) grid.appendChild(editor._formField(["chamber", k], k, ch[k], ps));
      }
    }

    const coolSchema = editor.resolver?.propSchema(editor.schema, "cooling");
    if (coolSchema) {
      for (const k of ["wall_material", "correlation"]) {
        const ps = editor.resolver.propSchema(coolSchema, k);
        if (ps) grid.appendChild(editor._formField(["cooling", k], k, cool[k], ps));
      }
    }
  }

  function buildGeometryToggles(editor, profileEditorsContainer, workspace) {
    const regen = editor.config.regen;
    const helix = regen.channels?.helix || {};
    const body = addSection(
      editor._regenFormRoot,
      "4 · Channel geometry",
      "Defaults: constant height, constant rib width, straight axial channels. Turn off a toggle to edit that parameter axially."
    );

    const toggleBar = document.createElement("div");
    toggleBar.className = "regen-geom-toggles";
    const toggles = [
      { id: "height", label: "Constant height" },
      { id: "rib", label: "Constant rib width" },
      { id: "wall", label: "Constant wall thickness" },
      { id: "helix", label: "Straight channels (β = 0)" },
    ];
    toggles.forEach(({ id, label }) => {
      const lbl = document.createElement("label");
      lbl.className = "regen-geom-toggle";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = isConstant(editor, id);
      cb.dataset.param = id;
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(` ${label}`));
      cb.addEventListener("change", () => {
        if (cb.checked) setConstantFromCurrent(editor, id);
        else setVariableFromCurrent(editor, id);
        editor._renderRegenProfiles?.();
        editor._notifyChange(true);
      });
      toggleBar.appendChild(lbl);
    });
    body.appendChild(toggleBar);

    const helixRow = document.createElement("div");
    helixRow.className = "form-grid regen-helix-options";
    addSelectField(helixRow, editor, "Helix handedness", ["regen", "channels", "helix", "handedness"],
      [["right", "Right-hand"], ["left", "Left-hand"]], helix.handedness || "right");
    addSelectField(helixRow, editor, "Profile interpolation", ["regen", "channels", "helix", "interp"],
      [["pchip", "PCHIP"], ["linear", "Linear"]], helix.interp || "pchip");
    body.appendChild(helixRow);

    const scalarGrid = document.createElement("div");
    scalarGrid.className = "form-grid regen-scalar-grid";
    body.appendChild(scalarGrid);

    const editorsWrap = document.createElement("div");
    editorsWrap.className = "regen-profile-editors";
    body.appendChild(editorsWrap);
    profileEditorsContainer.editorsWrap = editorsWrap;
    profileEditorsContainer.scalarGrid = scalarGrid;

    const syncEditors = () => {
      scalarGrid.innerHTML = "";
      editorsWrap.innerHTML = "";
      profileEditorsContainer.instances = {};

      toggles.forEach(({ id }) => {
        const spec = PARAM_SPECS[id];
        const constant = isConstant(editor, id);
        if (constant) {
          const field = document.createElement("div");
          field.className = "form-field";
          field.innerHTML = `<label>${spec.label} (${spec.unit})</label>`;
          const inp = document.createElement("input");
          inp.type = "number";
          inp.step = "any";
          const val = editor._getPath(spec.path);
          inp.value = isScalar(val) ? (val ?? spec.defaultVal) : (getBreakpoints(editor, id)[0]?.[1] ?? spec.defaultVal);
          inp.addEventListener("input", () => {
            const v = parseFloat(inp.value);
            if (Number.isNaN(v)) return;
            setConstant(editor, id, v, { notify: false });
          });
          inp.addEventListener("change", () => editor._notifyChange(true));
          const hint = document.createElement("span");
          hint.className = "field-unit-hint";
          hint.textContent = fmtVal(parseFloat(inp.value), spec);
          inp.addEventListener("input", () => {
            hint.textContent = fmtVal(parseFloat(inp.value), spec);
          });
          field.appendChild(inp);
          field.appendChild(hint);
          scalarGrid.appendChild(field);
        } else {
          const mount = document.createElement("div");
          mount.className = "regen-profile-editor-mount";
          mount.dataset.param = id;
          editorsWrap.appendChild(mount);
          const inst = new AxialProfileEditor(mount, editor, id, workspace);
          profileEditorsContainer.instances[id] = inst;
        }
      });
    };

    profileEditorsContainer.syncEditors = syncEditors;
    syncEditors();
  }

  function buildExportSection(editor) {
    const body = addSection(
      editor._regenFormRoot,
      "Report export defaults",
      "Settings used when running a full report. Live STL/STEP export is in section 6 below."
    );
    const grid = document.createElement("div");
    grid.className = "form-grid";
    body.appendChild(grid);
    for (const [label, path, def] of [
      ["Export STL on full report", ["regen", "export", "stl"], true],
      ["Export STEP on full report", ["regen", "export", "step"], false],
    ]) {
      addToggleField(grid, editor, label, path, editor._getPath(path) ?? def);
    }
  }

  function buildSyncSection(editor) {
    const body = addSection(
      editor._regenFormRoot,
      "Engine sync",
      "When enabled, values are taken from the RESA engine run instead of the regen YAML."
    );
    if (window.RegenEditor?.buildSyncMatrix) {
      body.appendChild(window.RegenEditor.buildSyncMatrix(editor, editor.config.regen?.sync || {}));
    }
  }

  function buildScalarCoolingFallback(editor) {
    const cool = editor.config.cooling || {};
    const body = addSection(
      editor._regenFormRoot,
      "Throat reference (scalar)",
      "Scalar cooling fields used until regen is enabled. These define the throat reference channel ring."
    );
    const grid = document.createElement("div");
    grid.className = "form-grid";
    body.appendChild(grid);
    grid.appendChild(editor._buildChannelCountRow(cool));
    grid.appendChild(editor._buildLayoutSummary(cool, editor.config.chamber || {}));

    const coolSchema = editor.resolver.propSchema(editor.schema, "cooling");
    const coolRows = editor._flattenObject(["cooling"], cool, coolSchema);
    for (const spec of [
      { keys: ["coolant", "inlet_T_K", "inlet_p_bar", "mdot_coolant_kg_s"] },
      { keys: ["channel_width_m", "channel_height_m", "rib_width_m", "inner_wall_thickness_m"] },
      { keys: ["wall_material", "correlation"] },
    ]) {
      for (const k of spec.keys) {
        const row = coolRows.find((r) => r.key === k);
        if (!row) continue;
        const field = ["channel_width_m", "channel_height_m", "rib_width_m", "inner_wall_thickness_m"].includes(k)
          ? editor._formDimField(row.path, row.key, row.value, row.schema)
          : editor._formField(row.path, row.key, row.value, row.schema);
        grid.appendChild(field);
      }
    }
  }

  function buildForm(editor, workspace) {
    const root = document.createElement("div");
    root.className = "regen-design-form";
    editor._regenFormRoot = root;

    if (!editor.config.regen) {
      root.appendChild(buildEnableRegenBlock(editor));
      buildScalarCoolingFallback(editor);
      return root;
    }

    buildCircuitSection(editor);
    buildCoolantSection(editor);
    buildWallSection(editor);

    const profileContainer = {};
    buildGeometryToggles(editor, profileContainer, workspace);
    editor._regenProfileContainer = profileContainer;
    editor._renderRegenProfiles = () => profileContainer.syncEditors?.();

    buildExportSection(editor);
    buildSyncSection(editor);
    return root;
  }

  window.RegenDesign = {
    PARAM_SPECS,
    AxialProfileEditor,
    buildForm,
    isConstant,
    getBreakpoints,
    setBreakpoints,
    setConstant,
    fmtVal,
  };
})();
