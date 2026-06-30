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

  /** Column-major 4×4 helpers for WebGL. */
  function mat4Identity() {
    const m = new Float32Array(16);
    m[0] = m[5] = m[10] = m[15] = 1;
    return m;
  }

  function mat4Multiply(a, b) {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) {
      for (let r = 0; r < 4; r++) {
        o[c * 4 + r] =
          a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] +
          a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
      }
    }
    return o;
  }

  function mat4RotateX(rad) {
    const c = Math.cos(rad), s = Math.sin(rad);
    const m = mat4Identity();
    m[5] = c; m[6] = s; m[9] = -s; m[10] = c;
    return m;
  }

  function mat4RotateY(rad) {
    const c = Math.cos(rad), s = Math.sin(rad);
    const m = mat4Identity();
    m[0] = c; m[2] = -s; m[8] = s; m[10] = c;
    return m;
  }

  function mat4Ortho(l, r, b, t, n, f) {
    const m = mat4Identity();
    m[0] = 2 / (r - l);
    m[5] = 2 / (t - b);
    m[10] = -2 / (f - n);
    m[12] = -(r + l) / (r - l);
    m[13] = -(t + b) / (t - b);
    m[14] = -(f + n) / (f - n);
    return m;
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

  function normalizeMesh(vertices) {
    const { center, extent } = meshBounds(vertices);
    const out = new Float32Array(vertices.length * 3);
    let j = 0;
    for (const v of vertices) {
      out[j++] = (v[0] - center[0]) / extent;
      out[j++] = (v[1] - center[1]) / extent;
      out[j++] = (v[2] - center[2]) / extent;
    }
    return out;
  }

  function regenProfilePoints(editor, paramKey) {
    const cfg = editor?.config?.regen;
    if (!cfg) return [];
    const map = {
      height_m: ["channels", "height"],
      rib_width_m: ["channels", "rib", "width"],
      wall_thickness_m: ["channels", "inner_wall_thickness"],
    };
    const path = map[paramKey];
    if (!path) return [];
    let obj = cfg;
    for (const k of path) obj = obj?.[k];
    if (typeof obj === "number") return [[-0.35, obj], [0.35, obj]];
    if (Array.isArray(obj) && obj.length && Array.isArray(obj[0])) return obj.map((p) => [p[0], p[1]]);
    return [];
  }

  function setRegenProfilePoint(editor, paramKey, idx, value) {
    const map = {
      height_m: ["regen", "channels", "height"],
      rib_width_m: ["regen", "channels", "rib", "width"],
      wall_thickness_m: ["regen", "channels", "inner_wall_thickness"],
    };
    const path = map[paramKey];
    if (!path) return;
    let obj = editor.config;
    for (let i = 0; i < path.length - 1; i++) obj = obj[path[i]];
    const key = path[path.length - 1];
    let prof = obj[key];
    if (typeof prof === "number") {
      prof = [[-0.35, prof], [0.35, prof]];
      obj[key] = prof;
    }
    if (!Array.isArray(prof)) return;
    if (prof[idx]) prof[idx][1] = value;
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
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.parentElement.getBoundingClientRect();
      const size = Math.min(rect.width - 8, 420);
      canvas.width = size * dpr;
      canvas.height = size * dpr;
      canvas.style.width = `${size}px`;
      canvas.style.height = `${size}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);

      if (!this.data?.contour) {
        ctx.fillStyle = "var(--text-muted)";
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

      ctx.strokeStyle = "var(--border)";
      ctx.lineWidth = 1;
      ctx.strokeRect(pad, pad, plot, plot);

      ctx.strokeStyle = "var(--accent)";
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
      ctx.strokeStyle = "var(--text-muted)";
      ctx.beginPath();
      const tx = toX(0);
      ctx.moveTo(tx, pad);
      ctx.lineTo(tx, pad + plot);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = "var(--text-muted)";
      ctx.font = "10px system-ui,sans-serif";
      ctx.fillText("throat", tx + 4, pad + 12);
      ctx.fillText("x (m)", pad + plot / 2 - 12, size - 6);
      ctx.save();
      ctx.translate(8, pad + plot / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText("r (m)", 0, 0);
      ctx.restore();

      if (this.showDims && dim.throat_radius_m) {
        this._drawDims(ctx, toX, toY, toYb, dim, xMin, xMax);
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

    _drawDims(ctx, toX, toY, toYb, dim, xMin, xMax) {
      const Rt = dim.throat_radius_m;
      const Rc = dim.chamber_radius_m;
      const Re = dim.exit_radius_m;
      const tx = toX(0);
      const ty = toY(Rt);
      const tyb = toYb(Rt);

      const drawLeader = (x1, y1, x2, y2, label, lx, ly) => {
        ctx.strokeStyle = "var(--warning)";
        ctx.fillStyle = "var(--warning)";
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
        ctx.fillStyle = "var(--text-muted)";
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
      window.addEventListener("mouseup", () => { this._drag = false; });
      window.addEventListener("mousemove", (e) => {
        if (!this._drag) return;
        this.rotY += (e.clientX - this._last[0]) * 0.01;
        this.rotX += (e.clientY - this._last[1]) * 0.01;
        this._last = [e.clientX, e.clientY];
        this.draw();
      });
      this._resizeObs = new ResizeObserver(() => this.draw());
      if (canvas.parentElement) this._resizeObs.observe(canvas.parentElement);
    }

    setData(payload) {
      this.data = payload;
      this.draw();
    }

    draw() {
      const gl = this.gl;
      if (!gl) return;
      const rect = this.canvas.parentElement.getBoundingClientRect();
      const w = Math.min(rect.width - 8, 420);
      const h = w;
      this.canvas.width = w;
      this.canvas.height = h;
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
      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
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
        ctx.fillStyle = "var(--text-muted)";
        ctx.font = "11px system-ui,sans-serif";
        ctx.fillText(String(err.message || err).slice(0, 100), 8, 20);
        ctx.restore();
      }
    }

    _drawImpl() {
      const ctx = this.ctx;
      const canvas = this.canvas;
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
        ctx.fillStyle = "var(--text-muted)";
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

      drawCircle(rGas, "var(--border)", "rgba(80,80,90,0.15)", 1);
      drawCircle(rInner, "var(--text-muted)", null, 1);

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
        ctx.fillStyle = "var(--warning)";
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
          ctx.fillStyle = "var(--accent)";
          ctx.globalAlpha = 0.75;
          ctx.fill();
          ctx.globalAlpha = 1;
          ctx.strokeStyle = "var(--accent)";
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }

      ctx.fillStyle = "var(--text-muted)";
      ctx.font = "10px system-ui,sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(`x = ${mm(this.section.x_m)} mm`, cx, size - 8);
      ctx.textAlign = "left";
      ctx.fillText(`N = ${N}`, 8, 14);
      ctx.fillText(`w = ${mm(st.channel_width_m)} mm`, 8, 26);
      ctx.fillText(`h = ${mm(st.channel_height_m)} mm`, 8, 38);
    }
  }

  /** Profile plot: contour background + editable station markers. */
  class ProfilePlotCanvas {
    constructor(canvas, onStationPick) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.data = null;
      this.activeParam = "height_m";
      this.stationIdx = 0;
      this.onStationPick = onStationPick || (() => {});
      canvas.addEventListener("click", (e) => this._pick(e));
      this._resizeObs = new ResizeObserver(() => this.draw());
      this._resizeObs.observe(canvas.parentElement || canvas);
    }

    setData(sectionPayload, paramKey) {
      this.data = sectionPayload;
      if (paramKey) this.activeParam = paramKey;
      this.draw();
    }

    setStationIdx(i) {
      this.stationIdx = i;
      this.draw();
    }

    _pick(e) {
      if (!this.data?.profiles) return;
      const rect = this.canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const xs = this.data.profiles.x_m;
      const pad = 36;
      const plotW = rect.width - pad * 2;
      const xMin = Math.min(...xs);
      const xMax = Math.max(...xs);
      const frac = (x - pad) / plotW;
      const xm = xMin + frac * (xMax - xMin);
      const i = xs.reduce((best, v, j) =>
        Math.abs(v - xm) < Math.abs(xs[best] - xm) ? j : best, 0);
      this.stationIdx = i;
      this.onStationPick(i, xs[i]);
      this.draw();
    }

    draw() {
      const ctx = this.ctx;
      const canvas = this.canvas;
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.parentElement.getBoundingClientRect();
      const w = rect.width - 8;
      const h = 200;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      if (!this.data?.profiles) return;

      const prof = this.data.profiles;
      const xs = prof.x_m;
      const ys = prof[this.activeParam] || prof.height_m;
      const xMin = Math.min(...xs);
      const xMax = Math.max(...xs);
      const yMax = Math.max(...ys) * 1.15;
      const pad = 36;
      const plotW = w - pad * 2;
      const plotH = h - pad * 2;
      const toX = (x) => pad + ((x - xMin) / (xMax - xMin)) * plotW;
      const toY = (y) => pad + plotH - (y / yMax) * plotH;

      if (this.data.contour) {
        const crs = this.data.contour.r_m;
        const rMax = Math.max(...crs);
        ctx.fillStyle = "rgba(100,120,160,0.12)";
        ctx.beginPath();
        for (let i = 0; i < xs.length; i++) {
          const xi = toX(xs[i]);
          const ri = (crs[Math.min(i, crs.length - 1)] / rMax) * plotH * 0.35;
          if (i === 0) ctx.moveTo(xi, pad + plotH);
          ctx.lineTo(xi, pad + plotH - ri);
        }
        ctx.lineTo(toX(xs[xs.length - 1]), pad + plotH);
        ctx.closePath();
        ctx.fill();
      }

      ctx.strokeStyle = "var(--accent)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < xs.length; i++) {
        const px = toX(xs[i]);
        const py = toY(ys[i]);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();

      const si = Math.min(this.stationIdx, xs.length - 1);
      const sx = toX(xs[si]);
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = "var(--warning)";
      ctx.beginPath();
      ctx.moveTo(sx, pad);
      ctx.lineTo(sx, pad + plotH);
      ctx.stroke();
      ctx.setLineDash([]);

      // Regen breakpoint markers
      if (this.breakpoints?.length) {
        ctx.fillStyle = "var(--warning)";
        for (const [bx, bv] of this.breakpoints) {
          const px = toX(bx);
          const py = toY(bv);
          ctx.beginPath();
          ctx.arc(px, py, 4, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = "var(--warning)";
          ctx.beginPath();
          ctx.moveTo(px, pad);
          ctx.lineTo(px, pad + plotH);
          ctx.stroke();
        }
      }
    }
  }

  /** Vertical sliders at regen profile breakpoints. */
  class ProfileBreakpointSliders {
    constructor(container, editor, workspace) {
      this.container = container;
      this.editor = editor;
      this.workspace = workspace;
      this.paramKey = "height_m";
    }

    setParam(paramKey) {
      this.paramKey = paramKey;
      this.render();
    }

    render() {
      this.container.innerHTML = "";
      const pts = regenProfilePoints(this.editor, this.paramKey);
      if (!pts.length || !this.editor.editable) {
        this.container.classList.add("hidden");
        return;
      }
      this.container.classList.remove("hidden");
      const head = document.createElement("p");
      head.className = "form-hint";
      head.textContent = "Drag sliders to edit profile breakpoints (regen)";
      this.container.appendChild(head);

      const row = document.createElement("div");
      row.className = "profile-breakpoints-row";
      const vmax = Math.max(...pts.map((p) => p[1]), 0.001) * 2.5;

      pts.forEach((pt, idx) => {
        const col = document.createElement("div");
        col.className = "profile-bp-col";
        col.innerHTML = `<span class="profile-bp-x">x=${(pt[0] * 1000).toFixed(0)} mm</span>`;
        const slider = document.createElement("input");
        slider.type = "range";
        slider.min = 0;
        slider.max = vmax;
        slider.step = vmax / 200;
        slider.value = pt[1];
        slider.orient = "vertical";
        slider.className = "profile-bp-slider";
        const val = document.createElement("span");
        val.className = "profile-bp-val";
        val.textContent = `${(pt[1] * 1000).toFixed(2)} mm`;
        slider.addEventListener("input", () => {
          const v = parseFloat(slider.value);
          setRegenProfilePoint(this.editor, this.paramKey, idx, v);
          val.textContent = `${(v * 1000).toFixed(2)} mm`;
          this.editor.onDirty(true);
          this.editor._notifyChange(false);
        });
        slider.addEventListener("change", () => {
          this.editor._notifyChange(true);
          this.workspace._fetchCooling();
        });
        col.appendChild(slider);
        col.appendChild(val);
        row.appendChild(col);
      });
      this.container.appendChild(row);
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
      window.addEventListener("mouseup", () => { this._drag = false; });
      window.addEventListener("mousemove", (e) => {
        if (!this._drag) return;
        this.rotY += (e.clientX - this._last[0]) * 0.01;
        this.rotX = Math.max(-1.2, Math.min(1.2, this.rotX + (e.clientY - this._last[1]) * 0.01));
        this._last = [e.clientX, e.clientY];
        this.draw();
      });
      this._resizeObs = new ResizeObserver(() => {
        const parent = this.canvas.parentElement;
        if (parent && !parent.classList.contains("hidden")) this.draw();
      });
      if (canvas.parentElement) this._resizeObs.observe(canvas.parentElement);
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
      this._debouncedThermal = debounce(() => this._fetchThermal(), 800);
      this._instances = new WeakMap();
      this._loadingCounts = new WeakMap();
      this._abort = { contour: null, cooling: null, cooling3d: null, thermal: null };
      this._seq = { contour: 0, cooling: 0, cooling3d: 0, thermal: 0 };
      this._mesh3dCache = null;
      this.thermalData = null;
      this._exportChannelId = 0;
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
      if (!this.cooling3dVisible && !this._mesh3dCache) {
        this._fetchCooling3d(null, { quiet: true });
      }
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
      this._debouncedContour();
      this._debouncedCooling();
      if (this.cooling3dVisible) this._debounced3d();
      if (this.editor?.config?.regen?.solver?.enabled !== false) {
        this._debouncedThermal();
      }
    }

    /** Refresh previews from current editor state (view or edit mode). */
    refresh() {
      this._fetchContour();
      this._fetchCooling();
      if (this.editor?.config?.regen) this._fetchCooling3d(null, { quiet: true });
      if (this.editor?.config?.regen?.solver?.enabled !== false) {
        this._fetchThermal();
      }
    }

    _drawProfileSpark(canvas, data, yKey, color, label) {
      const ctx = canvas.getContext("2d");
      if (!ctx || !data?.profiles) return;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.parentElement?.clientWidth || 280;
      const h = 88;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "var(--plot-bg, #0f1014)";
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
      ctx.fillStyle = "var(--text-muted, #888)";
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
        const kpis = panel.querySelector(".thermal-kpis");
        const spark = panel.querySelector(".ws-thermal-spark");
        const velSpark = panel.querySelector(".ws-velocity-spark");
        const note = panel.querySelector(".thermal-note");
        if (!this.thermalData) {
          if (kpis) kpis.innerHTML = "";
          if (note) note.textContent = "Click Preview thermal for a fast solve.";
          return;
        }
        if (this.thermalData.skipped) {
          if (note) note.textContent = this.thermalData.reason || "Thermal preview skipped.";
          return;
        }
        if (this.thermalData.error) {
          if (note) note.textContent = this.thermalData.error;
          return;
        }
        const s = this.thermalData.summary;
        if (s && kpis) {
          kpis.innerHTML = `
            <div class="thermal-kpi"><span>Q</span><strong>${s.Q_total_kW} kW</strong></div>
            <div class="thermal-kpi"><span>T_wall max</span><strong>${s.T_wall_max_K} K</strong></div>
            <div class="thermal-kpi"><span>Δp</span><strong>${s.dp_bar} bar</strong></div>
            <div class="thermal-kpi"><span>T_out</span><strong>${s.outlet_T_K} K</strong></div>
          `;
        }
        if (spark) this._drawThermalSpark(spark, this.thermalData);
        if (velSpark) this._drawVelocitySpark(velSpark, this.thermalData);
        if (note) {
          const n = this.thermalData.preview_stations;
          const warn = (this.thermalData.warnings || []).join(" · ");
          note.textContent = n
            ? `Fast preview · ${n} stations${warn ? ` · ${warn}` : ""}`
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
        const data = await postPreview("regen/thermal", cfg, {}, { signal });
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
      wraps.forEach((wrap) => {
        if (!hasData) this._loadingStart(wrap, "Updating contour…");
        else wrap.classList.add("is-stale");
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
        if (!this._isStale("contour", seq)) {
          wraps.forEach((wrap) => {
            wrap.classList.remove("is-stale");
            this._loadingEnd(wrap);
          });
        }
      }
    }

    async _fetchCooling3d(wrapFilter, { quiet = false } = {}) {
      const cfg = this.editor.getConfig();
      if (!cfg) return;
      const { signal, seq } = this._beginPreview("cooling3d");
      const wraps = wrapFilter ? [wrapFilter] : [...this._coolingWraps()];
      if (!quiet) {
        for (const wrap of wraps) {
          this._loadingStart(wrap, "Building channel 3D mesh…");
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
        if (!quiet && !this._isStale("cooling3d", seq)) {
          for (const wrap of wraps) {
            this._loadingEnd(wrap);
          }
        }
      }
    }

    async _fetchCooling(x_m) {
      const cfg = this.editor.getConfig();
      if (!cfg) return;
      const { signal, seq } = this._beginPreview("cooling");
      const hasData = !!this.sectionData?.station;
      for (const wrap of this._coolingWraps()) {
        if (!hasData) this._loadingStart(wrap, "Updating cross-section…");
        else wrap.classList.add("is-stale");
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
        if (!this._isStale("cooling", seq)) {
          for (const wrap of this._coolingWraps()) {
            wrap.classList.remove("is-stale");
            this._loadingEnd(wrap);
          }
        }
      }
    }

    mountChamberPanel(container) {
      const wrap = document.createElement("div");
      wrap.className = "workspace-preview";
      wrap.innerHTML = `
        <div class="workspace-loading hidden" aria-live="polite">
          <div class="workspace-spinner"></div>
          <span class="ws-loading-msg">Updating contour…</span>
        </div>
        <div class="workspace-preview-toolbar">
          <button type="button" class="btn-inline ws-view-2d active">2D contour</button>
          <button type="button" class="btn-inline ws-view-3d">3D chamber</button>
          <label class="toggle-inline ws-dims"><input type="checkbox" checked> Dimensions</label>
          <label class="toggle-inline ws-grid"><input type="checkbox" checked> Grid</label>
        </div>
        <p class="viewport-hint">Shift+drag or middle-click to pan · +/- to zoom · focus viewport for keys</p>
        <div class="workspace-canvas-wrap has-viewport-zoom">
          <canvas class="ws-chamber-2d"></canvas>
          <canvas class="ws-chamber-3d hidden"></canvas>
        </div>
        <p class="workspace-preview-hint ws-chamber-status"></p>
      `;
      container.appendChild(wrap);

      const c2d = wrap.querySelector(".ws-chamber-2d");
      const c3d = wrap.querySelector(".ws-chamber-3d");
      const contour = new ContourCanvas(c2d);
      const revolve = new ContourRevolve3D(c3d);
      this._instances.set(wrap, { contour, revolve, wrap });

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
      const wrap = document.createElement("div");
      wrap.className = "workspace-preview workspace-cooling regen-design-workspace";
      wrap.innerHTML = `
        <div class="workspace-loading hidden" aria-live="polite">
          <div class="workspace-spinner"></div>
          <span class="ws-loading-msg">Updating preview…</span>
        </div>

        <section class="regen-design-section regen-live-section">
          <h3 class="form-section-title">5 · Live analysis</h3>
          <p class="form-section-hint">Cross-section at an axial station, plus fast thermal solve along the full circuit.</p>
          <label class="workspace-slider-label">Axial position x (m)
            <input type="range" class="ws-axial-slider" step="any" />
            <span class="ws-axial-value">—</span>
          </label>
          <div class="workspace-canvas-wrap ws-cool-section-view has-viewport-zoom">
            <canvas class="ws-throat-section"></canvas>
          </div>
          <p class="workspace-preview-hint ws-cooling-status"></p>
          <div class="thermal-preview-panel hidden">
            <div class="thermal-kpis"></div>
            <div class="regen-thermal-plots">
              <div class="regen-plot-cell">
                <span class="regen-plot-label">Hot wall temperature</span>
                <canvas class="ws-thermal-spark"></canvas>
              </div>
              <div class="regen-plot-cell">
                <span class="regen-plot-label">Coolant velocity</span>
                <canvas class="ws-velocity-spark"></canvas>
              </div>
            </div>
            <div class="thermal-preview-actions">
              <button type="button" class="btn-inline ws-thermal-run">Run thermal preview</button>
              <span class="thermal-note form-hint"></span>
            </div>
          </div>
        </section>

        <section class="regen-design-section regen-3d-section">
          <h3 class="form-section-title">6 · 3D channel geometry &amp; export</h3>
          <p class="form-section-hint">Rotate the channel mesh. Export individual channels as STL or STEP for CAD.</p>
          <div class="workspace-preview-toolbar regen-export-toolbar">
            <label class="ws-export-channel-label">Channel
              <select class="ws-export-channel"></select>
            </label>
            <button type="button" class="btn-inline ws-cool-export-stl">Export STL</button>
            <button type="button" class="btn-inline ws-cool-export-step">Export STEP</button>
          </div>
          <div class="workspace-canvas-wrap ws-cool-3d-view has-viewport-zoom">
            <canvas class="ws-channel-3d"></canvas>
          </div>
        </section>
      `;
      container.appendChild(wrap);

      const section = new ThroatSectionCanvas(wrap.querySelector(".ws-throat-section"));
      const mesh3d = new ChannelMesh3D(wrap.querySelector(".ws-channel-3d"));
      mountViewportZoom(wrap.querySelector(".ws-cool-section-view"), () => section);
      mountViewportZoom(wrap.querySelector(".ws-cool-3d-view"), () => mesh3d);
      this._instances.set(wrap, { section, mesh3d, wrap, editor });

      const slider = wrap.querySelector(".ws-axial-slider");
      slider.addEventListener("input", () => {
        const x = parseFloat(slider.value);
        this.axialX = x;
        wrap.querySelector(".ws-axial-value").textContent = x.toFixed(4);
        this._fetchCooling(x);
      });

      const exportFmt = async (fmt) => {
        const cfg = editor.getConfig();
        const chSel = wrap.querySelector(".ws-export-channel");
        const channelId = chSel ? parseInt(chSel.value, 10) : 0;
        const res = await fetch("/api/preview/cooling/export-channel", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ config: cfg, channel_id: channelId, format: fmt }),
        });
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
      };
      wrap.querySelector(".ws-cool-export-stl").addEventListener("click", () =>
        exportFmt("stl").catch((e) => { wrap.querySelector(".ws-cooling-status").textContent = e.message; })
      );
      wrap.querySelector(".ws-cool-export-step").addEventListener("click", () =>
        exportFmt("step").catch((e) => { wrap.querySelector(".ws-cooling-status").textContent = e.message; })
      );
      wrap.querySelector(".ws-thermal-run")?.addEventListener("click", () => this._fetchThermal());

      this.cooling3dVisible = true;
      if (this.sectionData) this._applySectionToWrap(wrap);
      else this._debouncedCooling();
      this._fetchCooling3d(wrap, { quiet: true });
      this._updateThermalPanels();
      return wrap;
    }

    mountCoolingPanel(container, editor) {
      return this.mountRegenDesignPanel(container, editor);
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

    _regenProfilePath(paramKey) {
      const map = {
        height_m: ["regen", "channels", "height"],
        rib_width_m: ["regen", "channels", "rib", "width"],
        wall_thickness_m: ["regen", "channels", "inner_wall_thickness"],
      };
      return map[paramKey];
    }

    _setRegenProfileValue(editor, paramKey, stationIdx, value) {
      const path = this._regenProfilePath(paramKey);
      if (!path) return;
      let obj = editor.config;
      for (let i = 0; i < path.length - 1; i++) obj = obj[path[i]];
      const key = path[path.length - 1];
      let prof = obj[key];
      const xs = this.sectionData?.profiles?.x_m;
      if (!xs) return;
      const x = xs[stationIdx];
      if (!Array.isArray(prof)) {
        prof = [[xs[0], prof], [xs[xs.length - 1], prof]];
        obj[key] = prof;
      }
      let found = false;
      for (const pt of prof) {
        if (Math.abs(pt[0] - x) < 1e-9) {
          pt[1] = value;
          found = true;
          break;
        }
      }
      if (!found) {
        prof.push([x, value]);
        prof.sort((a, b) => a[0] - b[0]);
      }
    }

    _syncProfileValueSlider(wrap, editor, stationIdx) {
      const row = wrap.querySelector(".ws-profile-value-row");
      const slider = wrap.querySelector(".ws-profile-value");
      const lbl = wrap.querySelector(".ws-profile-value-label");
      if (!this.sectionData?.has_regen || !editor.editable) {
        row.classList.add("hidden");
        return;
      }
      row.classList.remove("hidden");
      const param = wrap.querySelector(".ws-profile-param").value;
      const ys = this.sectionData.profiles[param];
      const v = ys?.[stationIdx] ?? 0.001;
      slider.min = 0;
      slider.max = Math.max(v * 3, 0.006);
      slider.step = 0.0001;
      slider.value = v;
      lbl.textContent = (v * 1000).toFixed(2) + " mm";
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
})();
