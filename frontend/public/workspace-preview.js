/**
 * Design workspace — live chamber contour + cooling geometry previews.
 */
(function () {
  const PREVIEW_DEBOUNCE_MS = 400;

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  async function postPreview(path, config, extra = {}, options = {}) {
    const { signal } = options;
    const res = await fetch(`/api/preview/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config, ...extra }),
      signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      if (res.status === 501 && typeof detail === "string") {
        throw new Error(detail.includes("cadquery") || detail.includes("OCP")
          ? "STEP export requires cadquery-ocp. Install with: pip install cadquery-ocp"
          : detail);
      }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function mm(v) {
    return (v * 1000).toFixed(1);
  }

  const ZOOM_STEP = 1.25;
  const ZOOM_MIN = 0.35;
  const ZOOM_MAX = 5;

  function clampZoom(z) {
    return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
  }

  /** Pick a readable axis step in metres for grid lines. */
  function niceAxisStep(spanM, targetTicks = 6) {
    if (!spanM || spanM <= 0) return 0.01;
    const rough = spanM / targetTicks;
    const pow = Math.pow(10, Math.floor(Math.log10(rough)));
    const norm = rough / pow;
    let nice = 10;
    if (norm <= 1) nice = 1;
    else if (norm <= 2) nice = 2;
    else if (norm <= 5) nice = 5;
    return nice * pow;
  }

  function formatAxisM(v) {
    const a = Math.abs(v);
    if (a >= 1) return v.toFixed(2);
    if (a >= 0.1) return v.toFixed(3);
    if (a >= 0.01) return v.toFixed(4);
    return v.toExponential(1);
  }

  /**
   * Resolve theme CSS variables to concrete colors for Canvas 2D.
   * `ctx.fillStyle = "var(--x)"` is invalid and silently falls back to black,
   * so canvases must resolve variables via getComputedStyle. Called at the
   * start of each draw so theme switches are picked up automatically.
   */
  function canvasColors() {
    const s = getComputedStyle(document.documentElement);
    const get = (name, fallback) => s.getPropertyValue(name).trim() || fallback;
    return {
      accent: get("--accent", "#4a9eff"),
      border: get("--border", "#2a2d34"),
      warning: get("--warning", "#f0a030"),
      danger: get("--danger", "#e85d5d"),
      success: get("--success", "#3fb950"),
      textMuted: get("--text-muted", "#8b949e"),
      text: get("--text", "#e6e8eb"),
      plotBg: get("--plot-bg", "#0f1014"),
      bg: get("--bg", "#0f1014"),
    };
  }

  /** Parse a CSS color (#rgb, #rrggbb, rgb()/rgba()) to [r,g,b] in 0..1. */
  function cssColorToRgb(str, fallback) {
    const s = (str || "").trim();
    let m = /^#([0-9a-f]{3})$/i.exec(s);
    if (m) {
      return [0, 1, 2].map((i) => parseInt(m[1][i] + m[1][i], 16) / 255);
    }
    m = /^#([0-9a-f]{6})$/i.exec(s);
    if (m) {
      return [0, 1, 2].map((i) => parseInt(m[1].slice(i * 2, i * 2 + 2), 16) / 255);
    }
    m = /^rgba?\(([^)]+)\)$/i.exec(s);
    if (m) {
      const parts = m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);
      if (parts.length >= 3 && parts.slice(0, 3).every((v) => isFinite(v))) {
        return [parts[0] / 255, parts[1] / 255, parts[2] / 255];
      }
    }
    return fallback;
  }

  function mixRgb(a, b, t) {
    return [
      a[0] + (b[0] - a[0]) * t,
      a[1] + (b[1] - a[1]) * t,
      a[2] + (b[2] - a[2]) * t,
    ];
  }

  function attachViewMixin(viewer, { pan = false } = {}) {
    viewer.zoom = 1;
    viewer.panX = 0;
    viewer.panY = 0;
    viewer.zoomBy = (factor) => {
      viewer.zoom = clampZoom((viewer.zoom || 1) * factor);
      viewer.draw();
    };
    viewer.fitView = () => {
      viewer.zoom = 1;
      viewer.panX = 0;
      viewer.panY = 0;
      viewer.draw();
    };
    viewer.resetZoom = () => viewer.fitView();
    viewer._removeViewListeners = null;

    if (!pan || !viewer.canvas) return;

    let panning = false;
    let panLast = null;
    const canvas = viewer.canvas;

    const onPanMove = (e) => {
      if (!panning || !panLast) return;
      viewer.panX += e.clientX - panLast[0];
      viewer.panY += e.clientY - panLast[1];
      panLast = [e.clientX, e.clientY];
      viewer.draw();
    };
    const endPan = () => {
      panning = false;
      panLast = null;
      canvas.style.cursor = "";
    };

    canvas.addEventListener("mousedown", (e) => {
      if (e.button === 1 || (e.button === 0 && e.shiftKey)) {
        e.preventDefault();
        panning = true;
        panLast = [e.clientX, e.clientY];
        canvas.style.cursor = "grabbing";
      }
    });
    canvas.addEventListener("contextmenu", (e) => {
      if (e.button === 1) e.preventDefault();
    });
    window.addEventListener("mousemove", onPanMove);
    window.addEventListener("mouseup", endPan);
    viewer._removeViewListeners = () => {
      window.removeEventListener("mousemove", onPanMove);
      window.removeEventListener("mouseup", endPan);
    };
  }

  const attachZoomMixin = (viewer) => attachViewMixin(viewer, { pan: false });

  function mountViewportZoom(container, getViewer) {
    container.setAttribute("tabindex", "0");
    const bar = document.createElement("div");
    bar.className = "viewport-zoom";
    bar.innerHTML = `
      <button type="button" class="btn-zoom" data-zoom="in" aria-label="Zoom in">+</button>
      <button type="button" class="btn-zoom" data-zoom="out" aria-label="Zoom out">−</button>
      <button type="button" class="btn-zoom" data-zoom="fit" aria-label="Fit view">⊡</button>
      <button type="button" class="btn-zoom" data-zoom="reset" aria-label="Reset zoom">1×</button>
    `;
    bar.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-zoom]");
      if (!btn) return;
      const v = getViewer();
      if (!v?.zoomBy) return;
      const act = btn.dataset.zoom;
      if (act === "in") v.zoomBy(ZOOM_STEP);
      else if (act === "out") v.zoomBy(1 / ZOOM_STEP);
      else if (act === "fit") v.fitView();
      else v.resetZoom();
    });
    container.addEventListener("keydown", (e) => {
      const v = getViewer();
      if (!v?.zoomBy) return;
      if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        v.zoomBy(ZOOM_STEP);
      } else if (e.key === "-") {
        e.preventDefault();
        v.zoomBy(1 / ZOOM_STEP);
      } else if (e.key === "0") {
        e.preventDefault();
        v.fitView();
      }
    });
    container.appendChild(bar);
    return bar;
  }

  function meshBounds(vertices) {
    const min = [Infinity, Infinity, Infinity];
    const max = [-Infinity, -Infinity, -Infinity];
    for (const v of vertices) {
      for (let i = 0; i < 3; i++) {
        min[i] = Math.min(min[i], v[i]);
        max[i] = Math.max(max[i], v[i]);
      }
    }
    const center = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
    const extent = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2], 1e-9);
    return { center, extent };
  }

  /** 2D contour canvas — strict 1:1 axis scale (metres). */
  class ContourCanvas {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.data = null;
      this.showDims = true;
      this.showGrid = true;
      attachViewMixin(this, { pan: true });
      this._resizeObs = new ResizeObserver(() => this.draw());
      this._resizeObs.observe(canvas.parentElement || canvas);
    }

    destroy() {
      this._resizeObs?.disconnect();
      this._removeViewListeners?.();
    }

    setData(payload) {
      this.data = payload;
      this.draw();
    }

    setShowDims(on) {
      this.showDims = on;
      this.draw();
    }

    setShowGrid(on) {
      this.showGrid = on;
      this.draw();
    }

    draw() {
      const ctx = this.ctx;
      const canvas = this.canvas;
      const colors = canvasColors();
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.parentElement.getBoundingClientRect();
      const w = Math.max(rect.width, 48);
      const h = Math.max(rect.height, 48);
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const size = Math.min(w, h);
      ctx.translate((w - size) / 2, (h - size) / 2);

      if (!this.data?.contour) {
        ctx.fillStyle = colors.textMuted;
        ctx.font = "12px system-ui,sans-serif";
        ctx.fillText("Contour preview loading…", 12, 24);
        return;
      }

      const { x_m: xs, r_m: rs } = this.data.contour;
      const dim = this.data.contour.dimensions || {};
      const xMin = Math.min(...xs);
      const xMax = Math.max(...xs);
      const rMax = Math.max(...rs, dim.chamber_radius_m || 0) * 1.08;
      const pad = 28;
      const plot = size - pad * 2;
      const baseScale = plot / Math.max(xMax - xMin, 2 * rMax);
      const scale = baseScale * (this.zoom || 1);
      const xMid = (xMin + xMax) / 2;

      const toX = (x) => pad + plot / 2 + (x - xMid) * scale + (this.panX || 0);
      const toY = (r) => pad + plot / 2 - r * scale + (this.panY || 0);
      const toYb = (r) => pad + plot / 2 + r * scale + (this.panY || 0);

      if (this.showGrid) {
        this._drawGrid(ctx, { toX, toY, toYb, pad, plot, xMid, scale, size });
      }

      ctx.strokeStyle = colors.border;
      ctx.lineWidth = 1;
      ctx.strokeRect(pad, pad, plot, plot);

      ctx.strokeStyle = colors.accent;
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < xs.length; i++) {
        const px = toX(xs[i]);
        const py = toY(rs[i]);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();
      ctx.beginPath();
      for (let i = 0; i < xs.length; i++) {
        const px = toX(xs[i]);
        const py = toYb(rs[i]);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();

      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = colors.textMuted;
      ctx.beginPath();
      const tx = toX(0);
      ctx.moveTo(tx, pad);
      ctx.lineTo(tx, pad + plot);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = colors.textMuted;
      ctx.font = "10px system-ui,sans-serif";
      ctx.fillText("throat", tx + 4, pad + 12);
      ctx.fillText("x (m)", pad + plot / 2 - 12, size - 6);
      ctx.save();
      ctx.translate(8, pad + plot / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText("r (m)", 0, 0);
      ctx.restore();

      if (this.showDims && dim.throat_radius_m) {
        this._drawDims(ctx, toX, toY, toYb, dim, xMin, xMax, colors);
      }
    }

    _drawGrid(ctx, { toX, toY, toYb, pad, plot, xMid, scale, size }) {
      const xSpan = plot / scale;
      const rSpan = plot / scale;
      const xStep = niceAxisStep(xSpan);
      const rStep = niceAxisStep(rSpan);
      const xLo = xMid - xSpan / 2;
      const xHi = xMid + xSpan / 2;
      const rHi = rSpan / 2;

      ctx.save();
      ctx.lineWidth = 1;
      ctx.setLineDash([]);

      ctx.strokeStyle = "rgba(120, 128, 140, 0.22)";
      for (let x = Math.ceil(xLo / xStep) * xStep; x <= xHi + xStep * 0.001; x += xStep) {
        const px = toX(x);
        if (px < pad + 0.5 || px > pad + plot - 0.5) continue;
        ctx.beginPath();
        ctx.moveTo(px, pad);
        ctx.lineTo(px, pad + plot);
        ctx.stroke();
      }

      const cy = pad + plot / 2;
      ctx.beginPath();
      ctx.moveTo(pad, cy);
      ctx.lineTo(pad + plot, cy);
      ctx.strokeStyle = "rgba(120, 128, 140, 0.32)";
      ctx.stroke();

      ctx.strokeStyle = "rgba(120, 128, 140, 0.22)";
      for (let r = rStep; r <= rHi + rStep * 0.001; r += rStep) {
        for (const lineY of [toY(r), toYb(r)]) {
          if (lineY < pad + 0.5 || lineY > pad + plot - 0.5) continue;
          ctx.beginPath();
          ctx.moveTo(pad, lineY);
          ctx.lineTo(pad + plot, lineY);
          ctx.stroke();
        }
      }

      ctx.fillStyle = "rgba(140, 148, 160, 0.85)";
      ctx.font = "9px system-ui,sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      for (let x = Math.ceil(xLo / xStep) * xStep; x <= xHi + xStep * 0.001; x += xStep) {
        const px = toX(x);
        if (px < pad + 8 || px > pad + plot - 8) continue;
        ctx.fillText(formatAxisM(x), px, pad + plot + 3);
      }

      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (let r = 0; r <= rHi + rStep * 0.001; r += rStep) {
        if (r === 0) {
          ctx.fillText("0", pad - 4, cy);
          continue;
        }
        for (const py of [toY(r), toYb(r)]) {
          if (py < pad + 6 || py > pad + plot - 6) continue;
          ctx.fillText(formatAxisM(r), pad - 4, py);
        }
      }

      ctx.restore();
    }

    _drawDims(ctx, toX, toY, toYb, dim, xMin, xMax, colors) {
      const Rt = dim.throat_radius_m;
      const Rc = dim.chamber_radius_m;
      const Re = dim.exit_radius_m;
      const tx = toX(0);
      const ty = toY(Rt);
      const tyb = toYb(Rt);

      const drawLeader = (x1, y1, x2, y2, label, lx, ly) => {
        ctx.strokeStyle = colors.warning;
        ctx.fillStyle = colors.warning;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        ctx.font = "9px system-ui,sans-serif";
        ctx.fillText(label, lx, ly);
      };

      // Throat diameter
      drawLeader(tx - 18, ty, tx + 18, ty, `Rt ${mm(Rt)}`, tx + 22, ty - 2);
      drawLeader(tx - 18, tyb, tx + 18, tyb, "", tx + 22, tyb + 10);

      // Chamber diameter
      const xCyl = toX(xMin + (dim.chamber_length_m || 0) * 0.45);
      drawLeader(xCyl, toY(Rc), xCyl, toYb(Rc), `Rc ${mm(Rc)}`, xCyl + 4, toY(Rc) - 4);

      // Chamber length (injector to start of convergent)
      const xInj = toX(xMin);
      const xConv = toX(xMin + (dim.chamber_length_m || 0));
      const yTop = toY(Rc) - 8;
      ctx.beginPath();
      ctx.moveTo(xInj, yTop);
      ctx.lineTo(xConv, yTop);
      ctx.moveTo(xInj, yTop - 3);
      ctx.lineTo(xInj, yTop + 3);
      ctx.moveTo(xConv, yTop - 3);
      ctx.lineTo(xConv, yTop + 3);
      ctx.stroke();
      ctx.fillText(`Lcyl ${mm(dim.chamber_length_m || 0)}`, (xInj + xConv) / 2 - 18, yTop - 5);

      // Exit / expansion
      const xEx = toX(xMax);
      drawLeader(xEx, toY(Re), xEx, toYb(Re), `Re ${mm(Re)}`, xEx - 42, toY(Re) - 4);
      ctx.fillText(`ε ${dim.eps?.toFixed(1) || "—"}`, xEx - 28, toY(Re) + 14);

      // Convergent length hint
      if (dim.convergent_length_m) {
        ctx.fillStyle = colors.textMuted;
        ctx.fillText(`Lconv ${mm(dim.convergent_length_m)}`, tx - 52, ty - 14);
      }
    }
  }

  /** Simple WebGL revolve of contour profile (no Three.js dep). */
  class ContourRevolve3D {
    constructor(canvas) {
      this.canvas = canvas;
      this.gl = canvas.getContext("webgl", { antialias: true });
      this.data = null;
      this.rotY = 0.6;
      this.rotX = 0.35;
      attachZoomMixin(this);
      this._drag = false;
      this._last = null;
      canvas.addEventListener("mousedown", (e) => {
        this._drag = true;
        this._last = [e.clientX, e.clientY];
      });
      this._onWindowUp = () => { this._drag = false; };
      this._onWindowMove = (e) => {
        if (!this._drag) return;
        this.rotY += (e.clientX - this._last[0]) * 0.01;
        this.rotX += (e.clientY - this._last[1]) * 0.01;
        this._last = [e.clientX, e.clientY];
        this.draw();
      };
      window.addEventListener("mouseup", this._onWindowUp);
      window.addEventListener("mousemove", this._onWindowMove);
      this._resizeObs = new ResizeObserver(() => this.draw());
      if (canvas.parentElement) this._resizeObs.observe(canvas.parentElement);
    }

    destroy() {
      window.removeEventListener("mouseup", this._onWindowUp);
      window.removeEventListener("mousemove", this._onWindowMove);
      this._resizeObs?.disconnect();
      if (this.gl && this._buf) {
        this.gl.deleteBuffer(this._buf);
        this._buf = null;
      }
    }

    setData(payload) {
      this.data = payload;
      this.draw();
    }

    draw() {
      const gl = this.gl;
      if (!gl) return;
      const rect = this.canvas.parentElement.getBoundingClientRect();
      const w = Math.max(rect.width, 48);
      const h = Math.max(rect.height, 48);
      this.canvas.width = w;
      this.canvas.height = h;
      this.canvas.style.width = `${w}px`;
      this.canvas.style.height = `${h}px`;
      gl.viewport(0, 0, w, h);
      gl.clearColor(0.08, 0.09, 0.11, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);

      if (!this.data?.contour) return;

      const mesh = this._buildMesh(this.data.contour);
      const mvp = this._mvp(w / h);
      this._drawMesh(gl, mesh, mvp, [0.35, 0.55, 0.85, 1]);
    }

    _buildMesh(contour) {
      const xs = contour.x_m;
      const rs = contour.r_m;
      const segs = 48;
      const verts = [];
      const norms = [];
      for (let i = 0; i < xs.length - 1; i++) {
        const x0 = xs[i], r0 = rs[i], x1 = xs[i + 1], r1 = rs[i + 1];
        for (let j = 0; j < segs; j++) {
          const t0 = (j / segs) * Math.PI * 2;
          const t1 = ((j + 1) / segs) * Math.PI * 2;
          const push = (x, r, t) => {
            verts.push(x, r * Math.cos(t), r * Math.sin(t));
            const nr = Math.cos(t);
            const nz = Math.sin(t);
            norms.push(nr, 0, nz);
          };
          push(x0, r0, t0); push(x1, r1, t0); push(x1, r1, t1);
          push(x0, r0, t0); push(x1, r1, t1); push(x0, r0, t1);
        }
      }
      return { verts: new Float32Array(verts), norms: new Float32Array(norms) };
    }

    _mvp(aspect) {
      const cy = Math.cos(this.rotY), sy = Math.sin(this.rotY);
      const cx = Math.cos(this.rotX), sx = Math.sin(this.rotX);
      const s = 1.8 * (this.zoom || 1);
      return new Float32Array([
        cy * s, sx * sy * s, -cx * sy * s, 0,
        0, cx * s, sx * s, 0,
        sy * s, -sx * cy * s, cx * cy * s, 0,
        0, 0, -2.5, 1,
      ]);
    }

    _drawMesh(gl, mesh, mvp, color) {
      const vs = `
        attribute vec3 a_pos;
        attribute vec3 a_nrm;
        uniform mat4 u_mvp;
        varying vec3 v_n;
        void main() {
          v_n = a_nrm;
          gl_Position = u_mvp * vec4(a_pos, 1.0);
        }`;
      const fs = `
        precision mediump float;
        varying vec3 v_n;
        uniform vec4 u_col;
        void main() {
          float d = abs(v_n.z) * 0.5 + 0.5;
          gl_FragColor = vec4(u_col.rgb * (0.55 + 0.45 * d), 1.0);
        }`;
      const prog = this._program(gl, vs, fs);
      gl.useProgram(prog);
      // Create the vertex buffer once and reuse it — allocating a fresh
      // buffer per frame leaks GPU memory.
      if (!this._buf) this._buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this._buf);
      const inter = new Float32Array(mesh.verts.length + mesh.norms.length);
      for (let i = 0, j = 0; i < mesh.verts.length; i += 3, j += 6) {
        inter[j] = mesh.verts[i]; inter[j + 1] = mesh.verts[i + 1]; inter[j + 2] = mesh.verts[i + 2];
        inter[j + 3] = mesh.norms[i]; inter[j + 4] = mesh.norms[i + 1]; inter[j + 5] = mesh.norms[i + 2];
      }
      gl.bufferData(gl.ARRAY_BUFFER, inter, gl.STATIC_DRAW);
      const stride = 24;
      const aPos = gl.getAttribLocation(prog, "a_pos");
      const aNrm = gl.getAttribLocation(prog, "a_nrm");
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, stride, 0);
      gl.enableVertexAttribArray(aNrm);
      gl.vertexAttribPointer(aNrm, 3, gl.FLOAT, false, stride, 12);
      gl.uniformMatrix4fv(gl.getUniformLocation(prog, "u_mvp"), false, mvp);
      gl.uniform4fv(gl.getUniformLocation(prog, "u_col"), color);
      gl.drawArrays(gl.TRIANGLES, 0, mesh.verts.length / 3);
    }

    _program(gl, vs, fs) {
      if (this._prog) return this._prog;
      const v = gl.createShader(gl.VERTEX_SHADER);
      gl.shaderSource(v, vs);
      gl.compileShader(v);
      const f = gl.createShader(gl.FRAGMENT_SHADER);
      gl.shaderSource(f, fs);
      gl.compileShader(f);
      const p = gl.createProgram();
      gl.attachShader(p, v);
      gl.attachShader(p, f);
      gl.linkProgram(p);
      this._prog = p;
      return p;
    }
  }

  /** Throat cross-section at axial position x. */
  class ThroatSectionCanvas {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.section = null;
      attachViewMixin(this, { pan: true });
      this._resizeObs = new ResizeObserver(() => this.draw());
      this._resizeObs.observe(canvas.parentElement || canvas);
    }

    destroy() {
      this._resizeObs?.disconnect();
      this._removeViewListeners?.();
    }

    setData(section) {
      this.section = section;
      this.draw();
    }

    draw() {
      try {
        this._drawImpl();
      } catch (err) {
        const ctx = this.ctx;
        const canvas = this.canvas;
        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = canvasColors().textMuted;
        ctx.font = "11px system-ui,sans-serif";
        ctx.fillText(String(err.message || err).slice(0, 100), 8, 20);
        ctx.restore();
      }
    }

    _drawImpl() {
      const ctx = this.ctx;
      const canvas = this.canvas;
      const colors = canvasColors();
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.parentElement.getBoundingClientRect();
      const size = Math.min(rect.width - 8, 280);
      canvas.width = size * dpr;
      canvas.height = size * dpr;
      canvas.style.width = `${size}px`;
      canvas.style.height = `${size}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);

      if (!this.section?.station) {
        ctx.fillStyle = colors.textMuted;
        ctx.font = "12px system-ui,sans-serif";
        ctx.fillText("Section preview…", 12, 24);
        return;
      }

      const st = this.section.station;
      const cx = size / 2 + (this.panX || 0);
      const cy = size / 2 + (this.panY || 0);
      const rGas = Math.max(st.r_m, 1e-6);
      const rInner = rGas + Math.max(st.wall_thickness_m, 0);
      const rOuter = rInner + Math.max(st.channel_height_m, 0);
      const rExtent = Math.max(rOuter, rGas * 1.05, 1e-5);
      const scale = ((size * 0.42) / rExtent) * (this.zoom || 1);
      const minPx = 0.5;
      const toPx = (rM) => Math.max(rM * scale, minPx);

      const drawCircle = (rM, stroke, fill, lw = 1) => {
        const rp = toPx(rM);
        if (rp < minPx) return;
        ctx.beginPath();
        ctx.arc(cx, cy, rp, 0, Math.PI * 2);
        if (fill) { ctx.fillStyle = fill; ctx.fill(); }
        ctx.strokeStyle = stroke;
        ctx.lineWidth = lw;
        ctx.stroke();
      };

      drawCircle(rGas, colors.border, "rgba(80,80,90,0.15)", 1);
      drawCircle(rInner, colors.textMuted, null, 1);

      const N = Math.max(st.n_channels, 1);
      const rMid = 0.5 * (rInner + rOuter);
      const pitch = (2 * Math.PI) / N;
      const wAng = Math.max(
        0.02,
        Math.min(
          st.channel_width_m > 0 && rMid > 0 ? st.channel_width_m / rMid : pitch * 0.5,
          pitch * 0.85
        )
      );

      const rInnerPx = toPx(rInner);
      const rOuterPx = toPx(rOuter);
      const channelsFit = rOuter > rInner + 1e-9 && rOuterPx > rInnerPx + minPx;

      if (!channelsFit) {
        ctx.fillStyle = colors.warning;
        ctx.font = "10px system-ui,sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Channel height too large for this radius", cx, cy);
        ctx.textAlign = "left";
      } else {
        for (let k = 0; k < N; k++) {
          const a0 = k * pitch - wAng / 2;
          const a1 = k * pitch + wAng / 2;
          ctx.beginPath();
          ctx.arc(cx, cy, rOuterPx, a0, a1);
          ctx.arc(cx, cy, rInnerPx, a1, a0, true);
          ctx.closePath();
          ctx.fillStyle = colors.accent;
          ctx.globalAlpha = 0.75;
          ctx.fill();
          ctx.globalAlpha = 1;
          ctx.strokeStyle = colors.accent;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }

      ctx.fillStyle = colors.textMuted;
      ctx.font = "10px system-ui,sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(`x = ${mm(this.section.x_m)} mm`, cx, size - 8);
      ctx.textAlign = "left";
      ctx.fillText(`N = ${N}`, 8, 14);
      ctx.fillText(`w = ${mm(st.channel_width_m)} mm`, 8, 26);
      ctx.fillText(`h = ${mm(st.channel_height_m)} mm`, 8, 38);
    }
  }

  /**
   * Regen thermal margin plot — hot-wall temperature vs axial position with
   * the wall limit as a dashed line and green/red shading for the margin band.
   * Follows the same ResizeObserver + destroy() lifecycle as the other
   * canvases; all colors resolved through canvasColors() (never raw var()).
   */
  class MarginPlotCanvas {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.data = null;
      this.cursorX = null;
      this.showVelocity = false;
      this.onCursor = null;
      this._toX = null;
      this._fromX = null;
      this._resizeObs = new ResizeObserver(() => this.draw());
      this._resizeObs.observe(canvas.parentElement || canvas);
      canvas.addEventListener("mousemove", (e) => this._onMove(e));
      canvas.addEventListener("click", (e) => this._onMove(e, true));
    }

    destroy() {
      this._resizeObs?.disconnect();
    }

    setData(data) {
      this.data = data;
      this.draw();
    }

    setCursorX(x_m) {
      this.cursorX = x_m;
      this.draw();
    }

    _onMove(e, commit = false) {
      if (!this._fromX) return;
      const rect = this.canvas.getBoundingClientRect();
      const xMm = this._fromX(e.clientX - rect.left);
      const x_m = xMm / 1000;
      this.cursorX = x_m;
      this.draw();
      if (commit || e.type === "mousemove") this.onCursor?.(x_m, commit);
    }

    draw() {
      const ctx = this.ctx;
      if (!ctx) return;
      const canvas = this.canvas;
      const colors = canvasColors();
      const dpr = window.devicePixelRatio || 1;
      const parent = canvas.parentElement;
      const w = parent?.clientWidth || 320;
      const h = Math.max(parent?.clientHeight || 210, 160);
      if (w < 40) return;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = colors.plotBg;
      ctx.fillRect(0, 0, w, h);

      const prof = this.data?.profiles;
      const limit = this.data?.wall_limit_K ?? this.data?.summary?.wall_limit_K;
      const xs = prof?.x_m;
      const tw = prof?.T_wall_hot_K;
      if (!xs?.length || !tw?.length || limit == null) {
        ctx.fillStyle = colors.textMuted;
        ctx.font = "11px system-ui,sans-serif";
        ctx.fillText(
          this.data?.error ? "Thermal solve failed" : "Thermal margin — run thermal preview",
          10, 22
        );
        return;
      }

      const tc = prof.T_cool_K;
      const quality = prof.quality;
      const xsMm = xs.map((x) => x * 1000);
      const padL = 44, padR = 10, padT = 14, padB = 26;
      const pw = w - padL - padR;
      const ph = h - padT - padB;
      const xMin = Math.min(...xsMm);
      const xMax = Math.max(...xsMm);
      let yMin = Math.min(...tw, limit);
      let yMax = Math.max(...tw, limit);
      if (tc?.length) yMin = Math.min(yMin, ...tc);
      const yPad = Math.max((yMax - yMin) * 0.08, 5);
      yMin -= yPad;
      yMax += yPad;
      const toX = (xm) => padL + ((xm - xMin) / (xMax - xMin || 1)) * pw;
      const toY = (t) => padT + ph * (1 - (t - yMin) / (yMax - yMin || 1));
      this._toX = toX;
      this._fromX = (px) => xMin + ((px - padL) / (pw || 1)) * (xMax - xMin);

      // Grid + tick labels
      ctx.font = "9px system-ui,sans-serif";
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(120, 128, 140, 0.18)";
      ctx.fillStyle = colors.textMuted;
      const xStep = niceAxisStep(xMax - xMin, 6);
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      for (let x = Math.ceil(xMin / xStep) * xStep; x <= xMax + xStep * 1e-3; x += xStep) {
        const px = toX(x);
        ctx.beginPath();
        ctx.moveTo(px, padT);
        ctx.lineTo(px, padT + ph);
        ctx.stroke();
        ctx.fillText(x.toFixed(xStep < 1 ? 1 : 0), px, padT + ph + 4);
      }
      const yStep = niceAxisStep(yMax - yMin, 5);
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (let t = Math.ceil(yMin / yStep) * yStep; t <= yMax + yStep * 1e-3; t += yStep) {
        const py = toY(t);
        ctx.beginPath();
        ctx.moveTo(padL, py);
        ctx.lineTo(padL + pw, py);
        ctx.stroke();
        ctx.fillText(t.toFixed(0), padL - 4, py);
      }

      // Two-phase coolant underlay (0 < quality < 1)
      if (quality?.length === xs.length) {
        const bands = [];
        let start = null;
        for (let i = 0; i < quality.length; i++) {
          const twoPhase = quality[i] > 0 && quality[i] < 1;
          if (twoPhase && start == null) start = i;
          if (start != null && (!twoPhase || i === quality.length - 1)) {
            bands.push([start, twoPhase ? i : i - 1]);
            start = null;
          }
        }
        for (const [i0, i1] of bands) {
          const x0 = toX(xsMm[i0]);
          const x1 = toX(xsMm[i1]);
          ctx.save();
          ctx.globalAlpha = 0.1;
          ctx.fillStyle = colors.warning;
          ctx.fillRect(x0, padT, Math.max(x1 - x0, 2), ph);
          ctx.restore();
          if (x1 - x0 > 48) {
            ctx.fillStyle = colors.textMuted;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillText("two-phase", (x0 + x1) / 2, padT + 2);
          }
        }
      }

      // Margin band: shade between wall curve and limit line — green where
      // margin > 0, red where the curve exceeds the limit.
      const yLim = toY(limit);
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(toX(xsMm[0]), yLim);
      for (let i = 0; i < xsMm.length; i++) ctx.lineTo(toX(xsMm[i]), toY(tw[i]));
      ctx.lineTo(toX(xsMm[xsMm.length - 1]), yLim);
      ctx.closePath();
      ctx.clip();
      ctx.globalAlpha = 0.14;
      ctx.fillStyle = colors.success;
      ctx.fillRect(padL, yLim, pw, Math.max(padT + ph - yLim, 0));
      ctx.fillStyle = colors.danger;
      ctx.fillRect(padL, padT, pw, Math.max(yLim - padT, 0));
      ctx.restore();
      ctx.globalAlpha = 1;

      // Wall limit — horizontal dashed line + value label
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = colors.textMuted;
      ctx.beginPath();
      ctx.moveTo(padL, yLim);
      ctx.lineTo(padL + pw, yLim);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = colors.textMuted;
      ctx.font = "10px system-ui,sans-serif";
      ctx.textAlign = "right";
      const limitBelow = yLim - padT < 12;
      ctx.textBaseline = limitBelow ? "top" : "bottom";
      ctx.fillText(`wall limit ${Math.round(limit)} K`, padL + pw - 4, yLim + (limitBelow ? 3 : -3));

      // Coolant bulk temperature — thin muted context line
      if (tc?.length === xs.length) {
        ctx.strokeStyle = colors.textMuted;
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 0; i < xsMm.length; i++) {
          const px = toX(xsMm[i]);
          const py = toY(tc[i]);
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.stroke();
        ctx.font = "9px system-ui,sans-serif";
        ctx.textAlign = "left";
        ctx.textBaseline = "bottom";
        ctx.fillText("T_cool", toX(xsMm[0]) + 3, toY(tc[0]) - 3);
      }

      // Hot wall temperature curve
      ctx.strokeStyle = colors.danger;
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < xsMm.length; i++) {
        const px = toX(xsMm[i]);
        const py = toY(tw[i]);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();

      // Minimum-margin marker
      const s = this.data.summary || {};
      if (s.x_at_T_wall_max_m != null && s.min_margin_K != null) {
        const px = toX(s.x_at_T_wall_max_m * 1000);
        const py = toY(s.T_wall_max_K ?? Math.max(...tw));
        ctx.fillStyle = s.min_margin_K < 0 ? colors.danger : colors.accent;
        ctx.beginPath();
        ctx.arc(px, py, 3.5, 0, Math.PI * 2);
        ctx.fill();
        const label =
          `min margin ${Math.round(s.min_margin_K)} K @ x=${(s.x_at_T_wall_max_m * 1000).toFixed(0)} mm`;
        ctx.font = "10px system-ui,sans-serif";
        const onLeft = px > padL + pw / 2;
        ctx.textAlign = onLeft ? "right" : "left";
        ctx.textBaseline = "bottom";
        ctx.fillText(label, px + (onLeft ? -7 : 7), Math.max(py - 5, padT + 11));
      }

      // Frame + axis captions
      ctx.strokeStyle = colors.border;
      ctx.lineWidth = 1;
      ctx.strokeRect(padL, padT, pw, ph);
      ctx.fillStyle = colors.textMuted;
      ctx.font = "9px system-ui,sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "alphabetic";
      ctx.fillText("x (mm)", padL + pw / 2, h - 4);
      ctx.save();
      ctx.translate(10, padT + ph / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText("T_wall,hot (K)", 0, 0);
      ctx.restore();

      const vel = this.showVelocity ? prof.v_m_s : null;
      if (vel?.length === xs.length) {
        const vMin = Math.min(...vel);
        const vMax = Math.max(...vel);
        const toYv = (v) => padT + ph * (1 - (v - vMin) / (vMax - vMin || 1));
        ctx.strokeStyle = colors.accent;
        ctx.lineWidth = 1.2;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        for (let i = 0; i < xsMm.length; i++) {
          const px = toX(xsMm[i]);
          const py = toYv(vel[i]);
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = colors.accent;
        ctx.textAlign = "right";
        ctx.textBaseline = "top";
        ctx.fillText("v", padL + pw - 4, padT + 2);
      }

      if (this.cursorX != null) {
        const cx = toX(this.cursorX * 1000);
        ctx.strokeStyle = colors.accent;
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 3]);
        ctx.beginPath();
        ctx.moveTo(cx, padT);
        ctx.lineTo(cx, padT + ph);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      ctx.textAlign = "left";
    }
  }

  /** Channel mesh 3D — Canvas 2D painter's algorithm (reliable across browsers). */
  class ChannelMesh3D {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.mesh = null;
      this.normVerts = null;
      this.rotY = 0.85;
      this.rotX = 0.35;
      attachZoomMixin(this);
      this._needsRedraw = false;
      canvas.addEventListener("mousedown", (e) => {
        this._drag = true;
        this._last = [e.clientX, e.clientY];
      });
      this._onWindowUp = () => { this._drag = false; };
      this._onWindowMove = (e) => {
        if (!this._drag) return;
        this.rotY += (e.clientX - this._last[0]) * 0.01;
        this.rotX = Math.max(-1.2, Math.min(1.2, this.rotX + (e.clientY - this._last[1]) * 0.01));
        this._last = [e.clientX, e.clientY];
        this.draw();
      };
      window.addEventListener("mouseup", this._onWindowUp);
      window.addEventListener("mousemove", this._onWindowMove);
      this._resizeObs = new ResizeObserver(() => {
        const parent = this.canvas.parentElement;
        if (parent && !parent.classList.contains("hidden")) this.draw();
      });
      if (canvas.parentElement) this._resizeObs.observe(canvas.parentElement);
    }

    destroy() {
      window.removeEventListener("mouseup", this._onWindowUp);
      window.removeEventListener("mousemove", this._onWindowMove);
      this._resizeObs?.disconnect();
    }

    _rotate(v) {
      let x = v[0], y = v[1], z = v[2];
      const cy = Math.cos(this.rotY), sy = Math.sin(this.rotY);
      let x1 = x * cy + z * sy;
      let z1 = -x * sy + z * cy;
      const cx = Math.cos(this.rotX), sx = Math.sin(this.rotX);
      return [x1, y * cx - z1 * sx, y * sx + z1 * cx];
    }

    setData(payload) {
      this.mesh = payload;
      if (payload?.vertices?.length) {
        const { center, extent } = meshBounds(payload.vertices);
        this.normVerts = payload.vertices.map((v) => [
          (v[0] - center[0]) / extent,
          (v[1] - center[1]) / extent,
          (v[2] - center[2]) / extent,
        ]);
      } else {
        this.normVerts = null;
      }
      this._needsRedraw = true;
      this.draw();
    }

    draw() {
      const ctx = this.ctx;
      if (!ctx) {
        this._setStatus("Canvas not supported");
        return;
      }

      const parent = this.canvas.parentElement;
      if (!parent || parent.classList.contains("hidden")) {
        this._needsRedraw = true;
        return;
      }

      const rect = parent.getBoundingClientRect();
      const w = Math.max(Math.min(rect.width - 8, 420), 120);
      const h = w;
      if (w < 8) return;

      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = w * dpr;
      this.canvas.height = h * dpr;
      this.canvas.style.width = `${w}px`;
      this.canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#0f1014";
      ctx.fillRect(0, 0, w, h);

      if (!this.normVerts?.length || !this.mesh?.faces?.length) {
        ctx.fillStyle = "#8b949e";
        ctx.font = "12px system-ui,sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(this.mesh?.vertices ? "Empty mesh" : "Loading channel mesh…", w / 2, h / 2);
        return;
      }

      const scale = w * 0.38 * (this.zoom || 1);
      const cx = w / 2;
      const cy = h / 2;
      const tris = [];

      for (const face of this.mesh.faces) {
        const i0 = face[0], i1 = face[1], i2 = face[2];
        if (i0 >= this.normVerts.length || i1 >= this.normVerts.length || i2 >= this.normVerts.length) {
          continue;
        }
        const v0 = this._rotate(this.normVerts[i0]);
        const v1 = this._rotate(this.normVerts[i1]);
        const v2 = this._rotate(this.normVerts[i2]);
        const z = (v0[2] + v1[2] + v2[2]) / 3;
        tris.push({ z, pts: [v0, v1, v2] });
      }

      tris.sort((a, b) => a.z - b.z);

      for (const t of tris) {
        const d = (t.z + 1) * 0.5;
        const r = Math.round(45 + d * 70);
        const g = Math.round(110 + d * 90);
        const b = Math.round(190 + d * 50);
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.beginPath();
        for (let k = 0; k < 3; k++) {
          const px = cx + t.pts[k][0] * scale;
          const py = cy - t.pts[k][1] * scale;
          if (k === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.fill();
      }

      ctx.fillStyle = "#8b949e";
      ctx.font = "10px system-ui,sans-serif";
      ctx.textAlign = "left";
      ctx.fillText("Drag to rotate", 8, h - 8);
      this._needsRedraw = false;
    }

    _setStatus(msg) {
      const st = this.canvas.closest(".workspace-cooling")?.querySelector(".ws-cooling-status");
      if (st && msg) st.textContent = msg;
    }
  }

  /**
   * Wall + integrated-channel assembly viewer (WebGL, flat shading).
   *
   * Three vertex buffers, each interleaved [pos.xyz, nrm.xyz] with per-face
   * normals (vertices duplicated per triangle for a machined-metal look):
   *   - inner wall shell (revolved r_inner..r_floor) — rebuilt on data change
   *   - all N channel grooves (channel 0 curves instanced by rotation) —
   *     rebuilt on data change
   *   - closeout shell (revolved r_top..r_outer over the visible sector) —
   *     rebuilt on data change AND when the cutaway angle changes
   * Buffers are created lazily once, refilled via bufferData, and deleted in
   * destroy() (same leak-fix conventions as ContourRevolve3D).
   */
  class WallAssembly3D {
    constructor(canvas) {
      this.canvas = canvas;
      this.gl = canvas.getContext("webgl", { antialias: true });
      this.data = null;
      this.rotY = 0.9;
      this.rotX = 0.3;
      this.cutawayDeg = 90;
      this.show = { inner: true, channels: true, closeout: true };
      attachZoomMixin(this);
      this._bufs = { inner: null, channels: null, closeout: null };
      this._counts = { inner: 0, channels: 0, closeout: 0 };
      this._norm = null;
      this._drag = false;
      this._last = null;
      canvas.addEventListener("mousedown", (e) => {
        this._drag = true;
        this._last = [e.clientX, e.clientY];
      });
      this._onWindowUp = () => { this._drag = false; };
      this._onWindowMove = (e) => {
        if (!this._drag) return;
        this.rotY += (e.clientX - this._last[0]) * 0.01;
        this.rotX = Math.max(-1.35, Math.min(1.35, this.rotX + (e.clientY - this._last[1]) * 0.01));
        this._last = [e.clientX, e.clientY];
        this.draw();
      };
      window.addEventListener("mouseup", this._onWindowUp);
      window.addEventListener("mousemove", this._onWindowMove);
      this._resizeObs = new ResizeObserver(() => {
        const parent = this.canvas.parentElement;
        if (parent && !parent.classList.contains("hidden")) this.draw();
      });
      if (canvas.parentElement) this._resizeObs.observe(canvas.parentElement);
    }

    destroy() {
      window.removeEventListener("mouseup", this._onWindowUp);
      window.removeEventListener("mousemove", this._onWindowMove);
      this._resizeObs?.disconnect();
      const gl = this.gl;
      if (gl) {
        for (const key of Object.keys(this._bufs)) {
          if (this._bufs[key]) {
            gl.deleteBuffer(this._bufs[key]);
            this._bufs[key] = null;
          }
        }
        if (this._prog) {
          gl.deleteProgram(this._prog);
          this._prog = null;
        }
      }
    }

    setData(payload) {
      this.data = payload;
      if (payload?.profile?.x_m?.length) {
        const xs = payload.profile.x_m;
        const rOutMax = Math.max(...payload.profile.r_outer_m);
        const xMin = Math.min(...xs);
        const xMax = Math.max(...xs);
        this._norm = {
          cx: (xMin + xMax) / 2,
          ext: Math.max(xMax - xMin, 2 * rOutMax, 1e-9),
        };
        this._uploadInner();
        this._uploadChannels();
        this._uploadCloseout();
      } else {
        this._norm = null;
        this._counts = { inner: 0, channels: 0, closeout: 0 };
      }
      this.draw();
    }

    setCutaway(deg) {
      this.cutawayDeg = deg;
      if (this.data?.profile) this._uploadCloseout();
      this.draw();
    }

    setShow(part, on) {
      this.show[part] = !!on;
      this.draw();
    }

    /** Interleaved [pos, per-face normal] triangle writer into a Float32Array. */
    _writer(nTris) {
      const arr = new Float32Array(nTris * 3 * 6);
      let o = 0;
      const tri = (p0, p1, p2) => {
        const ux = p1[0] - p0[0], uy = p1[1] - p0[1], uz = p1[2] - p0[2];
        const vx = p2[0] - p0[0], vy = p2[1] - p0[1], vz = p2[2] - p0[2];
        let nx = uy * vz - uz * vy;
        let ny = uz * vx - ux * vz;
        let nz = ux * vy - uy * vx;
        const l = Math.hypot(nx, ny, nz) || 1;
        nx /= l; ny /= l; nz /= l;
        for (const p of [p0, p1, p2]) {
          arr[o++] = p[0]; arr[o++] = p[1]; arr[o++] = p[2];
          arr[o++] = nx; arr[o++] = ny; arr[o++] = nz;
        }
      };
      const quad = (p00, p01, p11, p10) => {
        tri(p00, p01, p11);
        tri(p00, p11, p10);
      };
      return { arr, tri, quad, used: () => o };
    }

    /** Normalized point on a revolved surface: axial x, radius r, angle th. */
    _rev(x, r, th) {
      const { cx, ext } = this._norm;
      return [(x - cx) / ext, (r * Math.cos(th)) / ext, (r * Math.sin(th)) / ext];
    }

    _upload(name, writer) {
      const gl = this.gl;
      if (!gl) return;
      const used = writer.used();
      const data = used === writer.arr.length ? writer.arr : writer.arr.subarray(0, used);
      if (!this._bufs[name]) this._bufs[name] = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this._bufs[name]);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      this._counts[name] = used / 6;
    }

    /** Revolve a [rLo, rHi] annular shell over [th0, th0+span]; end rings close it. */
    _shellTris(writer, xs, rLo, rHi, th0, span, segs) {
      const n = xs.length;
      for (let j = 0; j < segs; j++) {
        const t0 = th0 + (span * j) / segs;
        const t1 = th0 + (span * (j + 1)) / segs;
        for (let i = 0; i < n - 1; i++) {
          // outer surface (rHi) and inner surface (rLo)
          writer.quad(
            this._rev(xs[i], rHi[i], t0), this._rev(xs[i + 1], rHi[i + 1], t0),
            this._rev(xs[i + 1], rHi[i + 1], t1), this._rev(xs[i], rHi[i], t1)
          );
          writer.quad(
            this._rev(xs[i], rLo[i], t1), this._rev(xs[i + 1], rLo[i + 1], t1),
            this._rev(xs[i + 1], rLo[i + 1], t0), this._rev(xs[i], rLo[i], t0)
          );
        }
        // annular end rings
        for (const i of [0, n - 1]) {
          writer.quad(
            this._rev(xs[i], rLo[i], t0), this._rev(xs[i], rHi[i], t0),
            this._rev(xs[i], rHi[i], t1), this._rev(xs[i], rLo[i], t1)
          );
        }
      }
    }

    _uploadInner() {
      const p = this.data.profile;
      const n = p.x_m.length;
      const segs = 64;
      const w = this._writer(((n - 1) * 2 + 2) * segs * 2);
      this._shellTris(w, p.x_m, p.r_inner_m, p.r_floor_m, 0, Math.PI * 2, segs);
      this._upload("inner", w);
    }

    _uploadChannels() {
      const d = this.data;
      const c = d.channel;
      const n = d.n_stations;
      const N = d.n_channels;
      const { cx, ext } = this._norm;
      // per channel: 4 quad strips of (n-1) quads + 2 end caps (2 tris each)
      const w = this._writer(N * ((n - 1) * 4 * 2 + 4));
      const FL = new Array(n), FR = new Array(n), TL = new Array(n), TR = new Array(n);
      for (let k = 0; k < N; k++) {
        const phi = (2 * Math.PI * k) / N;
        const cp = Math.cos(phi), sp = Math.sin(phi);
        const rot = (p) => [
          (p[0] - cx) / ext,
          (p[1] * cp - p[2] * sp) / ext,
          (p[1] * sp + p[2] * cp) / ext,
        ];
        for (let i = 0; i < n; i++) {
          FL[i] = rot(c.floor_L[i]);
          FR[i] = rot(c.floor_R[i]);
          TL[i] = rot(c.top_L[i]);
          TR[i] = rot(c.top_R[i]);
        }
        for (let i = 0; i < n - 1; i++) {
          w.quad(FL[i], FL[i + 1], FR[i + 1], FR[i]);   // floor
          w.quad(TR[i], TR[i + 1], TL[i + 1], TL[i]);   // top
          w.quad(FR[i], FR[i + 1], TR[i + 1], TR[i]);   // side R
          w.quad(TL[i], TL[i + 1], FL[i + 1], FL[i]);   // side L
        }
        for (const i of [0, n - 1]) {                    // end caps
          w.tri(FL[i], FR[i], TR[i]);
          w.tri(FL[i], TR[i], TL[i]);
        }
      }
      this._upload("channels", w);
    }

    _uploadCloseout() {
      const p = this.data.profile;
      const n = p.x_m.length;
      const cut = (Math.max(0, Math.min(180, this.cutawayDeg)) * Math.PI) / 180;
      const span = Math.PI * 2 - cut;
      // cutaway sector centered on +z (theta = pi/2); model can be rotated
      const th0 = Math.PI / 2 + cut / 2;
      const segs = Math.max(1, Math.ceil((64 * span) / (Math.PI * 2)));
      const cutFaces = cut > 1e-6 ? 2 * (n - 1) * 2 : 0;
      const w = this._writer((((n - 1) * 2 + 2) * segs * 2) + cutFaces);
      this._shellTris(w, p.x_m, p.r_top_m, p.r_outer_m, th0, span, segs);
      if (cut > 1e-6) {
        // flat radial faces along the two cut planes so the shell reads solid
        for (const th of [th0, th0 + span]) {
          for (let i = 0; i < n - 1; i++) {
            w.quad(
              this._rev(p.x_m[i], p.r_top_m[i], th),
              this._rev(p.x_m[i + 1], p.r_top_m[i + 1], th),
              this._rev(p.x_m[i + 1], p.r_outer_m[i + 1], th),
              this._rev(p.x_m[i], p.r_outer_m[i], th)
            );
          }
        }
      }
      this._upload("closeout", w);
    }

    /**
     * Orthographic model-view-projection: rotation, then zoom applied to
     * x/y only. Clip-space z keeps a fixed scale so geometry never leaves
     * the [-1, 1] depth range at high zoom (a translated/zoomed z would
     * clip the whole mesh away).
     */
    _mvp() {
      const cy = Math.cos(this.rotY), sy = Math.sin(this.rotY);
      const cx = Math.cos(this.rotX), sx = Math.sin(this.rotX);
      const s = 1.3 * (this.zoom || 1);
      const zs = 0.9;
      return new Float32Array([
        cy * s, sx * sy * s, -cx * sy * zs, 0,
        0, cx * s, sx * zs, 0,
        sy * s, -sx * cy * s, cx * cy * zs, 0,
        0, 0, 0, 1,
      ]);
    }

    /** Pure rotation (column-major mat3) for lighting normals. */
    _rotMat() {
      const cy = Math.cos(this.rotY), sy = Math.sin(this.rotY);
      const cx = Math.cos(this.rotX), sx = Math.sin(this.rotX);
      return new Float32Array([
        cy, sx * sy, -cx * sy,
        0, cx, sx,
        sy, -sx * cy, cx * cy,
      ]);
    }

    _program(gl) {
      if (this._prog) return this._prog;
      const vs = `
        attribute vec3 a_pos;
        attribute vec3 a_nrm;
        uniform mat4 u_mvp;
        uniform mat3 u_rot;
        varying vec3 v_n;
        void main() {
          v_n = u_rot * a_nrm;
          gl_Position = u_mvp * vec4(a_pos, 1.0);
        }`;
      const fs = `
        precision mediump float;
        varying vec3 v_n;
        uniform vec3 u_col;
        void main() {
          vec3 n = normalize(v_n);
          float d = abs(dot(n, normalize(vec3(0.35, 0.5, 0.78))));
          gl_FragColor = vec4(u_col * (0.38 + 0.62 * d), 1.0);
        }`;
      const sh = (type, src) => {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        return s;
      };
      const p = gl.createProgram();
      gl.attachShader(p, sh(gl.VERTEX_SHADER, vs));
      gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(p);
      this._prog = p;
      this._loc = {
        pos: gl.getAttribLocation(p, "a_pos"),
        nrm: gl.getAttribLocation(p, "a_nrm"),
        mvp: gl.getUniformLocation(p, "u_mvp"),
        rot: gl.getUniformLocation(p, "u_rot"),
        col: gl.getUniformLocation(p, "u_col"),
      };
      return p;
    }

    _drawPart(name, col) {
      const gl = this.gl;
      const buf = this._bufs[name];
      const count = this._counts[name];
      if (!buf || !count) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      const stride = 24;
      gl.enableVertexAttribArray(this._loc.pos);
      gl.vertexAttribPointer(this._loc.pos, 3, gl.FLOAT, false, stride, 0);
      gl.enableVertexAttribArray(this._loc.nrm);
      gl.vertexAttribPointer(this._loc.nrm, 3, gl.FLOAT, false, stride, 12);
      gl.uniform3fv(this._loc.col, col);
      gl.drawArrays(gl.TRIANGLES, 0, count);
    }

    draw() {
      const gl = this.gl;
      if (!gl) return;
      const parent = this.canvas.parentElement;
      if (!parent || parent.classList.contains("hidden")) return;
      const rect = parent.getBoundingClientRect();
      const w = Math.max(Math.min(rect.width - 8, 460), 120);
      if (rect.width < 8) return;
      const h = w;
      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = Math.round(w * dpr);
      this.canvas.height = Math.round(h * dpr);
      this.canvas.style.width = `${w}px`;
      this.canvas.style.height = `${h}px`;
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);

      const colors = canvasColors();
      const bg = cssColorToRgb(colors.plotBg, [0.06, 0.063, 0.078]);
      gl.clearColor(bg[0], bg[1], bg[2], 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      if (!this.data?.profile || !this._norm) return;

      gl.useProgram(this._program(gl));
      gl.uniformMatrix4fv(this._loc.mvp, false, this._mvp());
      gl.uniformMatrix3fv(this._loc.rot, false, this._rotMat());

      const text = cssColorToRgb(colors.text, [0.9, 0.91, 0.92]);
      const border = cssColorToRgb(colors.border, [0.16, 0.18, 0.21]);
      const accent = cssColorToRgb(colors.accent, [0.29, 0.62, 1]);
      // Neutral machined-metal tones derived from theme text/border; the
      // closeout sits closer to the border tone so the two shells read apart
      // in both light and dark themes.
      if (this.show.inner) this._drawPart("inner", mixRgb(text, border, 0.45));
      if (this.show.channels) this._drawPart("channels", accent);
      if (this.show.closeout) this._drawPart("closeout", mixRgb(text, border, 0.72));
    }
  }

  class DesignWorkspace {
    constructor(editor) {
      this.editor = editor;
      this.contourData = null;
      this.sectionData = null;
      this.chamberView = "2d";
      this.coolingView = "section";
      this.axialX = null;
      this.cooling3dVisible = false;
      this._debouncedContour = debounce(() => this._fetchContour(), PREVIEW_DEBOUNCE_MS);
      this._debouncedCooling = debounce(() => this._fetchCooling(), PREVIEW_DEBOUNCE_MS);
      this._debounced3d = debounce(() => this._fetchCooling3d(), PREVIEW_DEBOUNCE_MS);
      this._debouncedAssembly3d = debounce(() => this._fetchAssembly3d(), PREVIEW_DEBOUNCE_MS);
      this._debouncedThermal = debounce(() => this._fetchThermal(), 800);
      this._instances = new WeakMap();
      this._mounted = [];
      this._loadingCounts = new WeakMap();
      this._abort = { contour: null, cooling: null, cooling3d: null, assembly3d: null, thermal: null };
      this._seq = { contour: 0, cooling: 0, cooling3d: 0, assembly3d: 0, thermal: 0 };
      this._mesh3dCache = null;
      this._assembly3dCache = null;
      this.thermalData = null;
      // Thermal preview fidelity — "preview" (reduced stations) or "full".
      // Session-scoped: lives on the workspace state object, no localStorage.
      this.thermalFidelity = "preview";
      this._exportChannelId = 0;
      this.geometryKind = "chamber";
      this._chamberWrap = null;
      this._coolingWrap = null;
      this._thermalWrap = null;
    }

    mountStage({ geometryEl, thermalEl }) {
      this.geometryEl = geometryEl;
      this.thermalEl = thermalEl;
      if (geometryEl && !this._chamberWrap) this.mountChamberPanel(geometryEl);
      if (geometryEl && !this._coolingWrap) this.mountCoolingGeometry(geometryEl);
      if (thermalEl && !this._thermalWrap) this.mountThermalPanel(thermalEl);
      this.setGeometryKind(this.geometryKind || "chamber");
    }

    setGeometryKind(kind) {
      this.geometryKind = kind === "cooling" ? "cooling" : "chamber";
      if (this._chamberWrap) this._chamberWrap.classList.toggle("hidden", this.geometryKind !== "chamber");
      if (this._coolingWrap) this._coolingWrap.classList.toggle("hidden", this.geometryKind !== "cooling");
      if (this.geometryKind === "cooling") {
        this.cooling3dVisible = true;
        this.prefetchCooling();
      }
      requestAnimationFrame(() => {
        this._refreshChamberCanvases();
        this._refreshCoolingCanvases();
        if (this._assembly3dCache) {
          const inst = this._coolingWrap && this._instances.get(this._coolingWrap);
          inst?.assembly3d?.draw?.();
        }
      });
    }

    setAxialX(x_m, { fetch = true } = {}) {
      if (!Number.isFinite(x_m)) return;
      this.axialX = x_m;
      const inst = this._thermalWrap && this._instances.get(this._thermalWrap);
      inst?.marginPlot?.setCursorX(x_m);
      for (const wrap of this._coolingWraps()) {
        const slider = wrap.querySelector(".ws-axial-slider");
        const valEl = wrap.querySelector(".ws-axial-value");
        if (slider) slider.value = x_m;
        if (valEl) valEl.textContent = x_m.toFixed(4);
      }
      if (fetch) this._fetchCooling(x_m);
    }

    /**
     * Destroy all viewer instances created by mount*Panel calls: removes
     * their window listeners, disconnects ResizeObservers, and frees GL
     * resources. Called by ConfigEditor._render before re-mounting panels.
     */
    destroyMounted() {
      for (const viewer of this._mounted) {
        viewer.destroy?.();
      }
      this._mounted = [];
    }

    _beginPreview(kind) {
      this._abort[kind]?.abort();
      const ac = new AbortController();
      this._abort[kind] = ac;
      const seq = ++this._seq[kind];
      return { signal: ac.signal, seq };
    }

    _isStale(kind, seq) {
      return seq !== this._seq[kind];
    }

    prefetchCooling() {
      this._fetchCooling();
      if (!this._assembly3dCache) this._fetchAssembly3d(null, { quiet: true });
      if (this.editor?.config?.regen?.solver?.enabled !== false) {
        this._debouncedThermal();
      }
    }

    _loadingStart(wrap, message = "Updating preview…") {
      const n = (this._loadingCounts.get(wrap) || 0) + 1;
      this._loadingCounts.set(wrap, n);
      const el = wrap.querySelector(".workspace-loading");
      if (el) {
        el.classList.remove("hidden");
        const msg = el.querySelector(".ws-loading-msg");
        if (msg) msg.textContent = message;
      }
      wrap.classList.add("is-loading");
    }

    _loadingEnd(wrap) {
      const n = Math.max(0, (this._loadingCounts.get(wrap) || 1) - 1);
      this._loadingCounts.set(wrap, n);
      if (n === 0) {
        wrap.querySelector(".workspace-loading")?.classList.add("hidden");
        wrap.classList.remove("is-loading");
      }
    }

    _coolingWraps() {
      return document.querySelectorAll(".workspace-cooling");
    }

    onConfigChange() {
      this._mesh3dCache = null;
      this._assembly3dCache = null;
      this._debouncedContour();
      this._debouncedCooling();
      if (this.cooling3dVisible) this._debouncedAssembly3d();
      if (this.editor?.config?.regen?.solver?.enabled !== false) {
        this._debouncedThermal();
      }
    }

    /** Refresh previews from current editor state (view or edit mode). */
    refresh() {
      this._fetchContour();
      this._fetchCooling();
      if (this.editor?.config?.regen) {
        this._fetchCooling3d(null, { quiet: true });
        this._fetchAssembly3d(null, { quiet: true });
      }
      if (this.editor?.config?.regen?.solver?.enabled !== false) {
        this._fetchThermal();
      }
    }

    _drawProfileSpark(canvas, data, yKey, color, label) {
      const ctx = canvas.getContext("2d");
      if (!ctx || !data?.profiles) return;
      const colors = canvasColors();
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.parentElement?.clientWidth || 280;
      const h = 88;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = colors.plotBg;
      ctx.fillRect(0, 0, w, h);
      const xs = data.profiles.x_m;
      const ys = data.profiles[yKey];
      if (!xs?.length || !ys?.length) return;
      const pad = 10;
      const xMin = Math.min(...xs);
      const xMax = Math.max(...xs);
      const yMin = Math.min(...ys);
      const yMax = Math.max(...ys);
      const toX = (x) => pad + ((x - xMin) / (xMax - xMin || 1)) * (w - pad * 2);
      const toY = (y) => pad + (h - pad * 2) * (1 - (y - yMin) / (yMax - yMin || 1));
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (let i = 0; i < xs.length; i++) {
        const px = toX(xs[i]);
        const py = toY(ys[i]);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();
      ctx.fillStyle = colors.textMuted;
      ctx.font = "9px system-ui,sans-serif";
      ctx.fillText(label, pad, h - 3);
    }

    _drawThermalSpark(canvas, data) {
      this._drawProfileSpark(canvas, data, "T_wall_hot_K", "#e85d5d", "T_wall hot (K)");
    }

    _drawVelocitySpark(canvas, data) {
      this._drawProfileSpark(canvas, data, "v_m_s", "#4a9eff", "Coolant velocity (m/s)");
    }

    _updateThermalPanels() {
      const regen = this.editor?.config?.regen;
      const show = !!regen && regen.solver?.enabled !== false;
      for (const wrap of this._coolingWraps()) {
        const panel = wrap.querySelector(".thermal-preview-panel");
        if (!panel) continue;
        panel.classList.toggle("hidden", !show);
        if (!show) continue;
        const data = this.thermalData;
        const inst = this._instances.get(wrap);
        const full = this.thermalFidelity === "full";
        panel.querySelector(".ws-fid-preview")?.classList.toggle("active", !full);
        panel.querySelector(".ws-fid-full")?.classList.toggle("active", full);
        const stations = panel.querySelector(".ws-station-count");
        if (stations) {
          stations.textContent = data?.ok && data.preview_stations
            ? (data.fidelity === "full"
              ? `${data.full_stations} stations`
              : `${data.preview_stations} of ${data.full_stations} stations`)
            : "";
        }
        if (inst?.marginPlot) {
          inst.marginPlot.setData(this.thermalData);
          if (this.axialX != null) inst.marginPlot.setCursorX(this.axialX);
        }
        const kpis = panel.querySelector(".thermal-kpis");
        const spark = panel.querySelector(".ws-thermal-spark");
        const velSpark = panel.querySelector(".ws-velocity-spark");
        const note = panel.querySelector(".thermal-note");
        if (!data) {
          if (kpis) kpis.innerHTML = "";
          if (note) note.textContent = "Click Preview thermal for a fast solve.";
          continue;
        }
        if (data.skipped) {
          if (note) note.textContent = data.reason || "Thermal preview skipped.";
          continue;
        }
        if (data.error) {
          if (note) note.textContent = data.error;
          continue;
        }
        const s = data.summary;
        if (s && kpis) {
          kpis.innerHTML = `
            <div class="thermal-kpi"><span>Q</span><strong>${s.Q_total_kW} kW</strong></div>
            <div class="thermal-kpi"><span>T_wall max</span><strong>${s.T_wall_max_K} K</strong></div>
            ${s.min_margin_K != null
              ? `<div class="thermal-kpi"><span>min margin</span><strong>${s.min_margin_K} K</strong></div>`
              : ""}
            <div class="thermal-kpi"><span>Δp</span><strong>${s.dp_bar} bar</strong></div>
            <div class="thermal-kpi"><span>T_out</span><strong>${s.outlet_T_K} K</strong></div>
          `;
        }
        if (spark) this._drawThermalSpark(spark, data);
        if (velSpark) this._drawVelocitySpark(velSpark, data);
        if (note) {
          const warn = (data.warnings || []).join(" · ");
          const label = data.fidelity === "full" ? "Full solve" : "Fast preview";
          note.textContent = data.preview_stations
            ? `${label}${warn ? ` · ${warn}` : ""}`
            : "";
        }
      }
    }

    async _fetchThermal() {
      const cfg = this.editor.getConfig();
      if (!cfg?.regen || cfg.regen.solver?.enabled === false) {
        this.thermalData = null;
        this._updateThermalPanels();
        return;
      }
      const { signal, seq } = this._beginPreview("thermal");
      for (const wrap of this._coolingWraps()) {
        const note = wrap.querySelector(".thermal-note");
        if (note) note.textContent = "Running thermal preview…";
      }
      try {
        const data = await postPreview(
          "regen/thermal", cfg,
          { fidelity: this.thermalFidelity || "preview" },
          { signal }
        );
        if (this._isStale("thermal", seq)) return;
        this.thermalData = data;
        this._updateThermalPanels();
      } catch (e) {
        if (e.name === "AbortError") return;
        if (this._isStale("thermal", seq)) return;
        this.thermalData = { error: e.message };
        this._updateThermalPanels();
      }
    }

    async _fetchContour() {
      const cfg = this.editor.getConfig();
      if (!cfg) return;
      const { signal, seq } = this._beginPreview("contour");
      const hasData = !!this.contourData?.contour;
      const wraps = document.querySelectorAll(".workspace-preview:not(.workspace-cooling)");
      const started = [];
      wraps.forEach((wrap) => {
        if (!hasData) {
          this._loadingStart(wrap, "Updating contour…");
          started.push(wrap);
        } else {
          wrap.classList.add("is-stale");
        }
      });
      try {
        const data = await postPreview("contour", cfg, {}, { signal });
        if (this._isStale("contour", seq)) return;
        this.contourData = data;
        this._refreshChamberCanvases();
      } catch (e) {
        if (e.name === "AbortError") return;
        if (this._isStale("contour", seq)) return;
        this.contourData = { error: e.message };
        this._refreshChamberCanvases();
      } finally {
        // Every _loadingStart must be balanced regardless of staleness/abort,
        // otherwise the overlay ref-count leaks and the spinner sticks.
        started.forEach((wrap) => this._loadingEnd(wrap));
        if (!this._isStale("contour", seq)) {
          wraps.forEach((wrap) => wrap.classList.remove("is-stale"));
        }
      }
    }

    async _fetchCooling3d(wrapFilter, { quiet = false } = {}) {
      const cfg = this.editor.getConfig();
      if (!cfg) return;
      const { signal, seq } = this._beginPreview("cooling3d");
      const wraps = wrapFilter ? [wrapFilter] : [...this._coolingWraps()];
      const started = [];
      if (!quiet) {
        for (const wrap of wraps) {
          this._loadingStart(wrap, "Building channel 3D mesh…");
          started.push(wrap);
        }
      }
      try {
        const data = await postPreview("cooling/3d", cfg, { channel_id: 0 }, { signal });
        if (this._isStale("cooling3d", seq)) return;
        this._mesh3dCache = data;
        for (const wrap of wraps) {
          const inst = this._instances.get(wrap);
          if (inst?.mesh3d) {
            inst.mesh3d.setData(data);
            requestAnimationFrame(() => inst.mesh3d.draw());
          }
          if (!quiet) {
            const st = wrap.querySelector(".ws-cooling-status");
            if (st) {
              st.textContent = `Channel 0 · ${data.vertices.length} verts · drag to rotate`;
            }
          }
        }
      } catch (e) {
        if (e.name === "AbortError") return;
        if (this._isStale("cooling3d", seq)) return;
        for (const wrap of wraps) {
          const st = wrap.querySelector(".ws-cooling-status");
          if (st) st.textContent = e.message;
        }
      } finally {
        // Balance every _loadingStart even for stale/aborted requests.
        for (const wrap of started) {
          this._loadingEnd(wrap);
        }
      }
    }

    _assemblyCaption(data) {
      if (!data?.ok) return "";
      return `${data.n_channels} channels · ${data.helical ? "helical" : "axial"}`;
    }

    async _fetchAssembly3d(wrapFilter, { quiet = false } = {}) {
      const cfg = this.editor.getConfig();
      if (!cfg) return;
      const { signal, seq } = this._beginPreview("assembly3d");
      const wraps = wrapFilter ? [wrapFilter] : [...this._coolingWraps()];
      const started = [];
      if (!quiet) {
        for (const wrap of wraps) {
          this._loadingStart(wrap, "Building wall assembly…");
          started.push(wrap);
        }
      }
      try {
        const data = await postPreview("cooling/assembly3d", cfg, {}, { signal });
        if (this._isStale("assembly3d", seq)) return;
        this._assembly3dCache = data;
        for (const wrap of wraps) {
          const inst = this._instances.get(wrap);
          if (inst?.assembly3d) {
            inst.assembly3d.setData(data);
            requestAnimationFrame(() => inst.assembly3d.draw());
          }
          const cap = wrap.querySelector(".ws-assembly-caption");
          if (cap) cap.textContent = this._assemblyCaption(data);
        }
      } catch (e) {
        if (e.name === "AbortError") return;
        if (this._isStale("assembly3d", seq)) return;
        for (const wrap of wraps) {
          const cap = wrap.querySelector(".ws-assembly-caption");
          if (cap) cap.textContent = e.message;
        }
      } finally {
        // Balance every _loadingStart even for stale/aborted requests.
        for (const wrap of started) {
          this._loadingEnd(wrap);
        }
      }
    }

    async _fetchCooling(x_m) {
      const cfg = this.editor.getConfig();
      if (!cfg) return;
      const { signal, seq } = this._beginPreview("cooling");
      const hasData = !!this.sectionData?.station;
      const started = [];
      for (const wrap of this._coolingWraps()) {
        if (!hasData) {
          this._loadingStart(wrap, "Updating cross-section…");
          started.push(wrap);
        } else {
          wrap.classList.add("is-stale");
        }
      }
      try {
        this.sectionData = await postPreview("cooling/section", cfg, {
          x_m: x_m ?? this.axialX ?? undefined,
        }, { signal });
        if (this._isStale("cooling", seq)) return;
        if (this.axialX == null) this.axialX = this.sectionData.x_throat_m;
        this._refreshCoolingCanvases();
      } catch (e) {
        if (e.name === "AbortError") return;
        if (this._isStale("cooling", seq)) return;
        this.sectionData = { error: e.message };
        this._refreshCoolingCanvases();
      } finally {
        // Balance every _loadingStart even for stale/aborted requests.
        for (const wrap of started) {
          this._loadingEnd(wrap);
        }
        if (!this._isStale("cooling", seq)) {
          for (const wrap of this._coolingWraps()) {
            wrap.classList.remove("is-stale");
          }
        }
      }
    }

    mountChamberPanel(container) {
      if (this._chamberWrap) return this._chamberWrap;
      const wrap = document.createElement("div");
      wrap.className = "workspace-preview";
      wrap.innerHTML = `
        <div class="workspace-loading hidden" aria-live="polite">
          <div class="workspace-spinner"></div>
          <span class="ws-loading-msg">Updating contour…</span>
        </div>
        <div class="workspace-preview-toolbar">
          <button type="button" class="btn-inline ws-view-2d active">2D</button>
          <button type="button" class="btn-inline ws-view-3d">3D</button>
          <label class="toggle-inline ws-dims"><input type="checkbox" checked> Dimensions</label>
          <label class="toggle-inline ws-grid"><input type="checkbox" checked> Grid</label>
        </div>
        <div class="workspace-canvas-wrap has-viewport-zoom">
          <canvas class="ws-chamber-2d"></canvas>
          <canvas class="ws-chamber-3d hidden"></canvas>
        </div>
        <p class="workspace-preview-hint ws-chamber-status"></p>
      `;
      container.appendChild(wrap);
      this._chamberWrap = wrap;

      const c2d = wrap.querySelector(".ws-chamber-2d");
      const c3d = wrap.querySelector(".ws-chamber-3d");
      const contour = new ContourCanvas(c2d);
      const revolve = new ContourRevolve3D(c3d);
      this._instances.set(wrap, { contour, revolve, wrap });
      this._mounted.push(contour, revolve);

      mountViewportZoom(wrap.querySelector(".workspace-canvas-wrap"), () =>
        c3d.classList.contains("hidden") ? contour : revolve
      );

      wrap.querySelector(".ws-view-2d").addEventListener("click", () => {
        this.chamberView = "2d";
        c2d.classList.remove("hidden");
        c3d.classList.add("hidden");
        wrap.querySelector(".ws-view-2d").classList.add("active");
        wrap.querySelector(".ws-view-3d").classList.remove("active");
        contour.draw();
      });
      wrap.querySelector(".ws-view-3d").addEventListener("click", () => {
        this.chamberView = "3d";
        c2d.classList.add("hidden");
        c3d.classList.remove("hidden");
        wrap.querySelector(".ws-view-3d").classList.add("active");
        wrap.querySelector(".ws-view-2d").classList.remove("active");
        revolve.draw();
      });
      wrap.querySelector(".ws-dims input").addEventListener("change", (e) => {
        contour.setShowDims(e.target.checked);
      });
      wrap.querySelector(".ws-grid input").addEventListener("change", (e) => {
        contour.setShowGrid(e.target.checked);
      });

      if (this.contourData) contour.setData(this.contourData);
      else this._debouncedContour();
      return wrap;
    }

    mountRegenDesignPanel(container, editor) {
      return this.mountCoolingGeometry(container, editor);
    }

    _exportChannel(fmt, wrap) {
      const editor = this.editor;
      const chSel = wrap.querySelector(".ws-export-channel")
        || this._coolingWrap?.querySelector(".ws-export-channel");
      const channelId = chSel ? parseInt(chSel.value, 10) : 0;
      return fetch("/api/preview/cooling/export-channel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: editor.getConfig(), channel_id: channelId, format: fmt }),
      }).then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          const detail = err.detail;
          if (res.status === 501 && typeof detail === "string") {
            throw new Error(
              detail.includes("cadquery") || detail.includes("OCP")
                ? "STEP export requires cadquery-ocp. Install with: pip install cadquery-ocp"
                : detail
            );
          }
          throw new Error(typeof detail === "string" ? detail : res.statusText);
        }
        const blob = await res.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `channel_${String(channelId).padStart(2, "0")}.${fmt}`;
        a.click();
        URL.revokeObjectURL(a.href);
      });
    }

    mountCoolingGeometry(container, editor) {
      if (this._coolingWrap) return this._coolingWrap;
      const ed = editor || this.editor;
      const wrap = document.createElement("div");
      wrap.className = "workspace-preview workspace-cooling regen-design-workspace";
      wrap.innerHTML = `
        <div class="workspace-loading hidden" aria-live="polite">
          <div class="workspace-spinner"></div>
          <span class="ws-loading-msg">Updating assembly…</span>
        </div>
        <div class="workspace-preview-toolbar assembly-controls">
          <label class="toggle-inline ws-asm-inner"><input type="checkbox" checked> Wall</label>
          <label class="toggle-inline ws-asm-channels"><input type="checkbox" checked> Channels</label>
          <label class="toggle-inline ws-asm-closeout"><input type="checkbox" checked> Closeout</label>
          <label class="workspace-slider-label ws-asm-cutaway-label">Cutaway
            <input type="range" class="ws-asm-cutaway" min="0" max="180" step="1" value="90" />
            <span class="ws-asm-cutaway-value">90°</span>
          </label>
          <label class="ws-export-channel-label">Ch
            <select class="ws-export-channel"></select>
          </label>
          <button type="button" class="btn-inline ws-cool-export-stl">STL</button>
          <button type="button" class="btn-inline ws-cool-export-step">STEP</button>
        </div>
        <div class="workspace-canvas-wrap ws-assembly-view has-viewport-zoom">
          <canvas class="ws-assembly-3d"></canvas>
        </div>
        <p class="workspace-preview-hint ws-assembly-caption"></p>
      `;
      container.appendChild(wrap);
      this._coolingWrap = wrap;

      const assembly3d = new WallAssembly3D(wrap.querySelector(".ws-assembly-3d"));
      mountViewportZoom(wrap.querySelector(".ws-assembly-view"), () => assembly3d);
      this._instances.set(wrap, { assembly3d, wrap, editor: ed });
      this._mounted.push(assembly3d);

      for (const [cls, part] of [
        ["ws-asm-inner", "inner"],
        ["ws-asm-channels", "channels"],
        ["ws-asm-closeout", "closeout"],
      ]) {
        wrap.querySelector(`.${cls} input`).addEventListener("change", (e) => {
          assembly3d.setShow(part, e.target.checked);
        });
      }
      const cutSlider = wrap.querySelector(".ws-asm-cutaway");
      cutSlider.addEventListener("input", () => {
        const deg = parseFloat(cutSlider.value) || 0;
        wrap.querySelector(".ws-asm-cutaway-value").textContent = `${Math.round(deg)}°`;
        assembly3d.setCutaway(deg);
      });
      wrap.querySelector(".ws-cool-export-stl").addEventListener("click", () =>
        this._exportChannel("stl", wrap).catch((e) => {
          wrap.querySelector(".ws-assembly-caption").textContent = e.message;
        })
      );
      wrap.querySelector(".ws-cool-export-step").addEventListener("click", () =>
        this._exportChannel("step", wrap).catch((e) => {
          wrap.querySelector(".ws-assembly-caption").textContent = e.message;
        })
      );

      this.cooling3dVisible = true;
      if (this._assembly3dCache) {
        assembly3d.setData(this._assembly3dCache);
        wrap.querySelector(".ws-assembly-caption").textContent = this._assemblyCaption(this._assembly3dCache);
      } else {
        this._fetchAssembly3d(wrap, { quiet: true });
      }
      if (this.sectionData) this._applySectionToWrap(wrap);
      return wrap;
    }

    mountThermalPanel(container, editor) {
      if (this._thermalWrap) return this._thermalWrap;
      const ed = editor || this.editor;
      const wrap = document.createElement("div");
      wrap.className = "workspace-preview workspace-cooling thermal-stage";
      wrap.innerHTML = `
        <div class="workspace-loading hidden" aria-live="polite">
          <div class="workspace-spinner"></div>
          <span class="ws-loading-msg">Thermal preview…</span>
        </div>
        <div class="regen-margin-head">
          <span class="regen-plot-label">Hot wall vs limit</span>
          <span class="thermal-fidelity">
            <button type="button" class="btn-inline ws-fid-preview active">Fast</button>
            <button type="button" class="btn-inline ws-fid-full">Full</button>
            <label class="toggle-inline ws-show-vel"><input type="checkbox"> Velocity</label>
            <span class="ws-station-count"></span>
          </span>
        </div>
        <div class="regen-margin-plot">
          <canvas class="ws-margin-plot"></canvas>
        </div>
        <div class="workspace-canvas-wrap ws-cool-section-view has-viewport-zoom">
          <canvas class="ws-throat-section"></canvas>
        </div>
        <label class="workspace-slider-label">Station
          <input type="range" class="ws-axial-slider" step="any" />
          <span class="ws-axial-value">—</span>
        </label>
        <div class="thermal-preview-panel">
          <div class="thermal-kpis"></div>
          <p class="thermal-note form-hint"></p>
        </div>
      `;
      container.appendChild(wrap);
      this._thermalWrap = wrap;

      const section = new ThroatSectionCanvas(wrap.querySelector(".ws-throat-section"));
      const marginPlot = new MarginPlotCanvas(wrap.querySelector(".ws-margin-plot"));
      mountViewportZoom(wrap.querySelector(".ws-cool-section-view"), () => section);
      this._instances.set(wrap, { section, marginPlot, wrap, editor: ed });
      this._mounted.push(section, marginPlot);

      let cursorTimer = 0;
      marginPlot.onCursor = (x_m, commit) => {
        this.axialX = x_m;
        const slider = wrap.querySelector(".ws-axial-slider");
        const valEl = wrap.querySelector(".ws-axial-value");
        if (slider) slider.value = x_m;
        if (valEl) valEl.textContent = x_m.toFixed(4);
        clearTimeout(cursorTimer);
        cursorTimer = setTimeout(() => this._fetchCooling(x_m), commit ? 0 : 80);
      };

      wrap.querySelector(".ws-show-vel input").addEventListener("change", (e) => {
        marginPlot.showVelocity = e.target.checked;
        marginPlot.draw();
      });

      const setFidelity = (fidelity) => {
        if (this.thermalFidelity === fidelity) return;
        this.thermalFidelity = fidelity;
        this._updateThermalPanels();
        this._fetchThermal();
      };
      wrap.querySelector(".ws-fid-preview").addEventListener("click", () => setFidelity("preview"));
      wrap.querySelector(".ws-fid-full").addEventListener("click", () => setFidelity("full"));

      wrap.querySelector(".ws-axial-slider").addEventListener("input", () => {
        const x = parseFloat(wrap.querySelector(".ws-axial-slider").value);
        this.setAxialX(x, { fetch: true });
      });

      if (this.sectionData) this._applySectionToWrap(wrap);
      else this._debouncedCooling();
      this._updateThermalPanels();
      this._debouncedThermal();
      return wrap;
    }

    _refreshChamberCanvases() {
      document.querySelectorAll(".workspace-preview").forEach((wrap) => {
        const inst = this._instances.get(wrap);
        if (!inst?.contour) return;
        const status = wrap.querySelector(".ws-chamber-status");
        if (this.contourData?.error) {
          if (status) status.textContent = this.contourData.error;
          return;
        }
        if (status && this.contourData?.summary) {
          const s = this.contourData.summary;
          status.textContent = `Rt ${mm(s.throat_radius_m)} mm · ε ${s.eps?.toFixed(1)} · F ${(s.thrust_N / 1000).toFixed(1)} kN`;
        }
        inst.contour.setData(this.contourData);
        inst.revolve.setData(this.contourData);
      });
    }

    _refreshCoolingCanvases() {
      document.querySelectorAll(".workspace-cooling").forEach((wrap) => {
        this._applySectionToWrap(wrap);
      });
    }

    _applySectionToWrap(wrap) {
      const inst = this._instances.get(wrap);
      if (!inst) return;
      const status = wrap.querySelector(".ws-cooling-status");
      if (this.sectionData?.error) {
        if (status) status.textContent = this.sectionData.error;
        return;
      }
      const slider = wrap.querySelector(".ws-axial-slider");
      if (slider && this.sectionData?.x_range) {
        slider.min = this.sectionData.x_range[0];
        slider.max = this.sectionData.x_range[1];
        slider.value = this.sectionData.x_m;
        const valEl = wrap.querySelector(".ws-axial-value");
        if (valEl) valEl.textContent = this.sectionData.x_m.toFixed(4);
      }
      inst.section?.setData(this.sectionData);

      const editor = inst.editor;
      const profileContainer = editor?._regenProfileContainer;
      if (profileContainer?.instances && this.sectionData) {
        for (const ed of Object.values(profileContainer.instances)) {
          ed.setSectionData(this.sectionData);
        }
      }

      if (status && this.sectionData?.station) {
        const st = this.sectionData.station;
        status.textContent =
          `x = ${mm(this.sectionData.x_m)} mm · N = ${st.n_channels} · ` +
          `w = ${mm(st.channel_width_m)} mm · h = ${mm(st.channel_height_m)} mm · β = ${st.beta_deg?.toFixed(1) ?? 0}°`;
      }
      const chSel = wrap.querySelector(".ws-export-channel");
      if (chSel && this.sectionData?.station) {
        const n = this.sectionData.station.n_channels || 1;
        const prev = parseInt(chSel.value, 10) || 0;
        chSel.innerHTML = "";
        for (let i = 0; i < n; i++) {
          const opt = document.createElement("option");
          opt.value = String(i);
          opt.textContent = String(i);
          chSel.appendChild(opt);
        }
        chSel.value = String(Math.min(prev, n - 1));
      }
      this._updateThermalPanels();
    }
  }

  window.DesignWorkspace = DesignWorkspace;
  window.postPreview = postPreview;
  window.StudioCanvas = { canvasColors };
})();
