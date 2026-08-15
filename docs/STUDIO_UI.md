# RESA Studio — UI redesign proposal

Proposal for a cleaner Studio: less chrome, one viewport for geometry and
plots, config as an inspector. Stack stays the same unless a later rewrite is
explicitly chosen.

Related: [STUDIO.md](STUDIO.md) (current behaviour), `frontend/public/`.

---

## 1. Current frontend stack

Studio is a **library-first Python app with a static SPA**, not a JS
framework project.

| Layer | What it is today |
|-------|------------------|
| Serve | FastAPI (`resa_studio/`) mounts `frontend/public/` at `/` and `/assets`, REST under `/api/` |
| App | Vanilla JS IIFEs, no bundler, no npm, no TypeScript |
| Scripts | `app.js` (shell, runs, plots, artifacts), `config-editor.js` (schema forms), `workspace-preview.js` (Canvas 2D + raw WebGL), `regen-design.js` (axial profiles), `regen-editor.js` (sync matrix), `studio-p2.js` (regen KPIs, sweep mini-charts, compare) |
| Style | Single `styles.css`, CSS custom properties, dark/light via `data-theme` |
| Live geometry | Custom Canvas 2D (contour, section, margin, sparks) + raw WebGL (chamber revolve, channel mesh, wall assembly). No Three.js |
| Full-run plots | Plotly figures written as standalone HTML (`include_plotlyjs="cdn"`, `plotly_white`) and shown in an **iframe** |
| Reports | Same Plotly HTML + matplotlib PDF (`resa/reporting/`) |

That stack is a good fit for `pip install` / `python -m resa_studio`. Clutter
is an **information-architecture** problem, not a missing React/Next.js
problem. A framework rewrite would not, by itself, make the data presentation
better.

```
┌ header: brand + tagline + Auto-run + Validate + Run fast + Full report + theme + health
├────────────┬──────────────────────────────┬────────────┐
│ Sidebar    │ Workspace (vertical stack)   │ Artifacts  │
│ 260px      │                              │ 200px      │
│            │ toolbar: "Config" + full path│            │
│ Pinned     │                              │ file list  │
│ Recent     │ CARD Results                 │ (plots     │
│ Projects   │   KPIs, warnings, notes,     │  duplicated│
│ Campaigns  │   sweep mini-charts,         │  as links) │
│ Compare A/B│   provenance <details>       │            │
│ Saved runs │                              │            │
│  (KPI      │ CARD Configuration           │            │
│   table    │   Design|Analyze|Propellants │            │
│   8 cols   │   |Combustion|Chamber|Regen  │            │
│   in 260px)│   |Off-design                │            │
│            │   + live canvases INSIDE tabs│            │
│            │                              │            │
│            │ CARD Visualizations          │            │
│            │   plot tabs + Plotly iframe  │            │
└────────────┴──────────────────────────────┴────────────┘
```

Typical 1440×900 window: **~460px of chrome columns** plus a 44px topbar,
then three stacked titled cards. Geometry and plots never get a full stage.

---

## 2. Why it feels cluttered and ugly

### Chrome repeats the same facts

| Surface | What it currently says |
|---------|------------------------|
| Topbar | `RESA Studio` + `Sizing & Analysis` + four run controls + `Light`/`Dark` + `Connecting…` |
| Workspace toolbar | `Config` + `configs/projects/e2_c1/design.yaml` + validation badge |
| Card headers | `Results`, `Configuration` (+ `Viewing`/`Editing`), `Visualizations` (+ `Saved run`/`Live run`), `Artifacts` |
| Editor | Design/Analyze switch **and** Design/Analyze tabs; seven tabs; numbered regen sections `1 ·` … `7 ·` |
| Plotly iframe | Its own title (`Contour — rao_bell`, `Regen channel geometry — colored by …`) on top of the tab name |
| Canvases | Hints like `Shift+drag or middle-click to pan · +/- to zoom · focus viewport for keys` always visible |

Almost none of that needs to be a heading. Context belongs in one breadcrumb.

### Two visualization systems, never composed

1. **Live previews** live *inside* Chamber / Regen tabs (small canvases,
   stacked, competing with forms).
2. **Full-run Plotly** lives in a *separate* Visualizations card, one iframe
   at a time, `plotly_white` on a dark page, ~480px tall.

The chamber contour is therefore drawn twice (canvas + iframe). Cooling is
drawn three times (section canvas, channel WebGL, assembly WebGL) plus later
Plotly 3D HTML. Off-design is a row of 100px sparkline canvases in Results
*and* full Plotly tabs below.

### Sidebar is a junk drawer

Six blocks in 260px: Pinned, Recent, Projects, Campaigns, Compare A/B,
Saved runs. The runs “list” is a sortable **eight-column KPI table**
(`min-width: 400px`) inside that column — horizontal scroll, 0.72rem type,
emoji pin/edit. Compare also exists as shift+click, two `<select>`s, a
Results `<details>`, and a pin-baseline button.

### Regen cooling is a vertical novel

The Regen tab concatenates:

1. Circuit / helix / wall / solver / export / sync forms (numbered 1–4+)
2. **5 · Live analysis** — axial slider, section canvas, thermal KPIs,
   margin plot, two sparkline plots, fidelity toggle, run button
3. **6 · 3D channel geometry** — second WebGL view + STL/STEP
4. **7 · Wall assembly** — third WebGL view + layer toggles + cutaway

An engineer looking at wall temperature vs the material limit has to scroll
past forms, then past a cross-section, then past two more 3D views. The
assembly viewer already *contains* the channels; the dedicated channel-mesh
view is largely redundant.

### Plots are files, not a figure system

`renderPlots` tabs every `*.html` artifact. Labels come from filenames
(`e2_c1_regen_3d` → `e2 c1 regen 3d`). There is no grouping (geometry /
thermal / off-design), no shared x-axis, no dark template, no in-app
colorbars. The artifacts rail duplicates those same HTML files as links.

---

## 3. Design principles for the new variant

1. **One stage.** Geometry and plots share a persistent viewport. Forms never
   bury the picture.
2. **One place per fact.** Project, config, run, and validation appear once
   (top breadcrumb). No card titles that restate the region.
3. **Nav is a file picker, not a dashboard.** Runs are names and age; KPIs
   live on the stage.
4. **Linked views beat stacked views.** Cross-section, wall cutaway, and
   T(x) share one axial station. Hovering a plot moves the 3D cut plane.
5. **Quiet chrome.** Toolbars appear on hover or in compact icon groups.
   Plotly/canvas titles are omitted when the tab already names the figure.
6. **Keep the stack.** Restructure HTML/CSS/JS first. Do not introduce a
   bundler unless in-app Plotly.js or a 3D library is adopted later.

---

## 4. Proposed layout — inspector + viewport

CAE pattern (Fusion, Ansys, OpenRocket, RPA): **files left, picture centre,
parameters right.**

```
┌ RESA    e2_c1 / design.yaml    · valid     [Edit]  [Run ▾]  ☀ ┐
├──────────┬─────────────────────────────────┬───────────────────┤
│ e2_c1    │                                 │ Design            │
│  design  │                                 │  Thrust      10 kN│
│  asbuilt │         VIEWPORT                │  Pc          30   │
│  hf02    │     (geometry or plot)          │  O/F         5.5  │
│          │                                 │                   │
│ Runs     │                                 │ Chamber           │
│  14:02 · │─────────────────────────────────│  Contour   Rao    │
│  11:18   │  10.2 kN   242 s   30.1 bar     │  CR         8     │
│          │  Thrust    Isp     Pc           │                   │
│          │  [Geometry | Thermal | Sweep]   │ Regen             │
└──────────┴─────────────────────────────────┴───────────────────┘
```

### Topbar (one row, ~40px)

- Mark `RESA` only — drop `Studio` and `Sizing & Analysis`.
- Breadcrumb `project / config` (not the `configs/projects/…` path). Click
  the project name to reveal the file tree if the sidebar is collapsed.
- Validation as a dot + tooltip (`valid` / `3 errors`), not a badge next to
  a path.
- **Edit** (toggles inspector lock) and a single **Run** split button
  (Fast = default, Full report in the menu). Auto-run as a check in that
  menu. Drop the always-visible Validate button (validate on blur already).
- Theme as an icon. Health only when disconnected.

### Left nav (~200px, two sections)

- **Projects** tree. Pin is a hover star on the row. Recent is the top of
  the same list (or a single “Recent” disclosure), not a second tree.
- **Runs** — compact rows: label (or hash8), relative age, warning count.
  Click opens that run on the stage. Shift+click still sets compare B.
  The eight-column KPI table moves to a **Compare** view (see §6).

Campaigns: a `…` menu on the project, or a secondary “Campaigns” item that
replaces the run list when chosen — not a fourth permanent block.

Compare A/B `<select>`s: remove. Compare is a mode entered from two selected
runs.

### Centre — viewport (the product)

A single pane that fills leftover height. Mode strip at the **bottom** of
the pane (overlay, not a titled card):

| Mode | Contents |
|------|----------|
| **Geometry** | Chamber 2D/3D *or* cooling assembly 3D, depending on inspector tab. One canvas. |
| **Thermal** | Margin-first T_wall vs limit, with T_cool / velocity as optional overlays. Linked to the 3D cut plane. |
| **Sweeps** | Off-design (ox throttle, O/F, envelope) after a run. |
| **Report** | Full-run Plotly/PDF figures, grouped, still in this pane. |

A **KPI strip** sits on the bottom edge of the viewport (or just under it):
Thrust, Isp, Pc, O/F, ε, and when regen is on T_wall,max + min margin + Δp.
Provenance (`input` / `calculated` / `optimized`) is a tooltip on the value,
not a third line on every tile and not a default table.

Warnings: one amber chip on the strip (`2 warnings`); expand inline.

Notes / pin-baseline / provenance table: behind a `⋯` on the strip.

### Right — inspector (~320px)

The current Configuration card, minus the page-width header.

- No `Configuration` / `Viewing` chrome. Edit vs locked is the topbar
  **Edit** control.
- Tabs become a **short stack of sections** (Design, Propellants, Chamber,
  Regen, Off-design) with one section expanded. Seven equal tabs plus a
  Design/Analyze switch is two ways to say the same thing.
- Design vs Analyze is a single segmented control at the top of the
  inspector (keep), and the Design/Analyze *tabs* go away.
- Chamber fields sit beside the geometry viewport; regen fields beside the
  assembly viewport. Live canvases **leave the inspector**.
- Numbered `1 · Regen circuit` headings become ordinary section labels
  without the index and without the paragraph of hint under every title.
  Hints move to field-level `title` / a `?` affordance.

### Artifacts rail — delete the column

Recover 200px for the viewport. Artifacts become:

- PDF / CSV / STL / STEP as actions on the Run menu and on Geometry
  (export already exists for STL/STEP).
- HTML plots open in Report mode; they are not a parallel file browser.

---

## 5. Data presentation — graphs and 3D

### 5.1 One 3D scene for cooling

Replace stacked “channel mesh” + “wall assembly” with **one assembly
viewer** (the newer WebGL path):

- Layers: inner wall, channels, closeout (existing toggles).
- Cutaway slider (existing).
- Optional: color channels by T_wall / q / v when a thermal preview or
  full solve exists (Plotly 3D already does this for reports; the live
  viewer should too).
- Channel STL/STEP export stays as a toolbar action, not a reason for a
  second viewport.

Chamber 3D (revolve) stays on the Geometry mode when the inspector is on
Chamber. 2D contour is the default for sizing (equal-aspect, dimensions on
demand) — 3D is a toggle in the viewport corner, not a second page of
chrome (`2D contour` / `3D chamber` text buttons become icons).

### 5.2 Thermal: one linked figure, not three canvases

Today: margin plot + T_wall spark + velocity spark, plus KPI chips, plus a
cross-section.

Proposed **Thermal** mode:

```
T_wall (hot) ────────
T_limit - - - - - - -     min-margin callout at x*
T_cool  ·············
        |                 vertical cursor = axial station
        +—— section / 3D cut updates
```

- Primary: wall temperature vs axial x, limit as a dashed line, two-phase
  band if present (keep the margin-first idea).
- Secondary axis or toggle: coolant velocity / quality / Δp cumulative.
- Cross-section is a **small inset** (or a split, 70/30) driven by the same
  cursor — not a full-width canvas above the plots.
- Fast preview vs full stations: a single control in the viewport toolbar
  (`Fast` / `Full`), not a labelled “fidelity” cluster.

Fast-run off-design sparklines in the Results card go away; Sweeps mode
shows the same data at a readable size, then Report mode swaps in the
Plotly envelope when a full run exists.

### 5.3 Report plots: group, restyle, stop using a white iframe blindly

Short term (no Plotly.js in the browser):

- Group tabs: **Geometry** (contour, mach, 3D), **Thermal** (regen
  dashboard, 3D colored), **Off-design** (throttle, O/F, envelope).
- Human labels from a map, not filename mangling.
- Generate Plotly with `template="plotly_dark"` (or a small custom
  template using Studio tokens) and `margin` with `t` near 32, **no figure
  title** when the tab already names it.
- Iframe height: `flex: 1` to fill the viewport, not `min(480px, 55vh)`.

Better (one extra script tag, still no bundler): ship Plotly.js from a
CDN or vendored file, have `/api/runs/...` return **figure JSON** (Plotly
`to_json`) or the CSV already written, and `Plotly.react` into a div.
That lets the Studio theme drive the figure, shared cursor with the 3D
view, and removes iframe chrome.

### 5.4 KPI strip

Fewer, larger numbers. Drop per-tile source lines (`calculated`,
`regen solver`) — tooltip or a single “i” on the strip.

Suggested set:

- Always: Thrust, Isp, Pc, O/F, ε
- Regen: T_wall,max (with limit in muted text), min margin, Δp
- Delta vs baseline as a small signed chip on the number (keep), not extra
  cards

Throat radius and mdot are secondary (hover or expanded strip).

---

## 6. Compare and campaigns

**Compare** is a dedicated centre view, not a sidebar widget:

- Select two runs in the list (shift+click stays).
- Viewport shows a KPI delta table + overlay plots (contour, T_wall(x)).
- The current `<details>Run comparison</details>` dump and the two
  dropdowns go away.

**Campaigns** launch from the project `…` menu or a top-level view that
reuses the run list (campaign outputs already go to a separate out dir).
Progress/status can occupy the KPI strip while a campaign runs.

---

## 7. Visual language (still CSS tokens)

Keep the existing dark/light tokens; change hierarchy:

- **Fewer borders.** Cards inside cards (every `.config-section` is a
  boxed island) should become simple heading + fields on `--surface`.
- **Type:** one size for UI (14px), KPIs at ~22px tabular, section labels
  12px medium — not uppercase 0.6–0.65rem everywhere.
- **Accent** only for the active nav row, primary Run, and plot highlights.
  Stop accent-tinting regen plot tabs, regen KPI borders, and editor
  “is-editing” box-shadow at once.
- **Viewport background** `--plot-bg` full-bleed; inspector and nav stay
  `--bg-elevated`. The picture should feel like the working surface, not
  another card on a stack.
- **No emoji in chrome** (📌 ✎ 📄 ↻). Use SVG or text (`Pin`, `Edit`).

---

## 8. What not to do

- **Do not rewrite in React/Vue/Next** for this cleanup. The SPA is ~8 JS
  files served by FastAPI; a bundler would fight the `pip install`
  workflow. Revisit only if Plotly.js + a real 3D library become core
  and the IIFE graph is unmaintainable.
- **Do not add Three.js** until the single-scene assembly viewer is the
  only 3D path. Raw WebGL is already doing the job; the issue is three
  canvases, not shader quality.
- **Do not keep live previews inside the form** “and also” a big viewport —
  that recreates today’s duplication.
- **Do not put the KPI table back in the sidebar.**

---

## 9. Implementation sequence (same stack)

Each step should look better on its own; no big-bang rewrite.

1. **Shell IA** — `index.html` + `styles.css` + `app.js` layout: drop
   artifacts column, collapse sidebar to Projects + Runs, move Results
   into a KPI strip, move Visualizations into a flex viewport pane,
   inspector on the right. Card `<h2>`s and the workspace path toolbar
   go away.
2. **Regen viewport** — hoist live canvases out of
   `mountRegenDesignPanel` / `mountChamberPanel` into the centre pane;
   inspector keeps forms only. Merge channel-mesh into assembly; delete
   section 6 as a separate WebGL view.
3. **Thermal figure** — one margin-first plot with overlays; section as
   inset; shared axial cursor.
4. **Plotly restyle** — dark template, no redundant titles, grouped tabs,
   iframe fills the pane.
5. **Compare view** — sidebar dropdowns removed; delta table + overlay in
   the viewport.
6. **Optional:** Plotly.js in-page from figure JSON; color 3D mesh by
   thermal preview.

No API changes required for 1–5 (preview and artifact routes already
exist). Step 6 may add a `format=json` on plot endpoints or reuse CSV.

---

## 10. Success criteria

- Geometry or the active plot uses **most of the window** at 1280×800,
  not a strip under two other cards.
- A new user can read T_wall vs limit and the cutaway assembly **without
  scrolling the regen form**.
- Topbar + section headers no longer repeat project, config, and “Results
  / Configuration / Visualizations”.
- Sidebar does not horizontally scroll.
- Dark theme Plotly no longer flashes a white page in the iframe.
- FastAPI + static JS + CSS remains the only frontend toolchain.
