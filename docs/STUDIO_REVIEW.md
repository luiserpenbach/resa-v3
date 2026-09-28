# RESA Studio review and revision 2

This document reviews the Studio as it was before revision 2, which is now
served at `/classic/`, and explains how revision 2 answers the brief:

- simpler and friendlier
- a great-looking interface
- fast results for whatever is needed, from a first hand calculation to
  detailed cooling-channel design
- a professional project workflow with bounded workspaces, one design per
  configuration, plain wording and version tracking
- deployable to a host like Vercel

## 1. What the previous Studio got right

These carry over into revision 2.

- **One physics core.** The UI drove the same library as the CLI, with the
  config schema as the single source of truth and warnings that carry their
  provenance.
- **Live previews.** The contour and cooling-layout previews reran on every
  edit, backed by a cached pipeline.
- **Engineering depth.** The regen solver covers regime switching, the Bartz
  band, the radiation-cooled skirt, the feed-pressure budget, and wall
  stress and strain. Axial profile editors, run labels and baseline deltas
  were also useful.
- **No framework lock-in.** The frontend was plain JavaScript with no
  runtime dependencies.

## 2. Findings

The review read the frontend (~9,000 lines of JS/CSS), the FastAPI adapters
and routes, and the physics modules. It also ran the app and every example
design.

### 2.1 Workflow: the full configuration gated every answer

| Finding | Consequence |
|---|---|
| The UI opens one YAML file and presents it as tabs of raw config sections: Design, Propellants, Combustion, Chamber, Regen cooling, Off-design. | To get "roughly what Isp and throat size?" you first need a project, a config file and the edit mode. |
| Any what-if needs *Edit* first; auto-run only works in edit mode. | Exploration is slow and modal. |
| Fast runs never include cooling results. Plots only exist after a *Full report* written to disk. | Heat flux and wall temperature, the numbers engineers most often want, sit behind the slowest path. |
| The regen thermal preview reran on every edit on every tab. Every tab switch rebuilt all viewers and refetched contour, section, 3D, assembly and thermal data. | Wasted compute and a jittery UI. |
| No heat-flux estimate without a full channel layout. No p–h diagram anywhere; the only coolant-state plot was T–ρ, inside the report HTML. | The two things named in the brief, "estimate the heat flux" and "study the p–h diagram", were not directly reachable. |

### 2.2 Concepts, duplication and jargon

- **Two cooling descriptions.** Both a `cooling:` block and a `regen:` block
  existed. Only `regen` drives the solver; `cooling` feeds a throat-fit check.
  The regen tab still edited `cooling.wall_material` and
  `cooling.correlation`, which had no effect, and showed correlation hints for
  the wrong correlation set. The channel count synced between the blocks, but
  width, height and wall thickness did not, which triggered
  "cooling block disagrees" warnings. Channel fill % was computed three
  different ways.
- **Jargon in labels.** Examples: `η c*`, `ε`, `L*`, "Bartz correction",
  "Width reference: Mid height/Floor", "PCHIP", "Engine sync", `hot_gas_*`,
  raw provenance codes, "config", "Folder id", "engine · mode · hash" run
  names, and save confirmations listing dotted config paths.
- **Units.** Millimetre-scale geometry was entered in metres (`0.0008`), and
  axial stations too.
- **Fields with no UI.** `film_cooling`, `nozzle_flow`,
  `use_delivery_temperatures`, `eta_cf_source`, most `solver.*`, the skirt,
  and two sync flags. For example, film-cooling validation errors could not be
  navigated to.

### 2.3 Project workflow

- Projects were folders of loosely related YAML files tied together by `base:`
  inheritance and `../shared/` fragment references. What belonged to a design
  was not bounded.
- There was no version history. Saves overwrote files. Drafts lived in
  `localStorage` keyed by path.
- Runs were keyed by config hash. Full reports posted the inline editor
  dictionary, so reports showed the config as "(inline)" and could contain
  unsaved edits.
- Campaign outputs were not listed among runs. There was no delete, rename,
  duplicate or branch.

### 2.4 Deployability

- Nearly every example uses `backend: rocketcea`. rocketcea needs a Fortran
  compiler, so outside a developer machine almost nothing ran. That includes
  this review's container and any serverless host. The error surfaced only as
  a red validation message.
- The API assumed a writable repository: reports went to `out/`, and saves
  went into `configs/`. There was no storage abstraction.
- **rocketcea is not thread-safe.** FastAPI runs synchronous endpoints in a
  thread pool. Two concurrent calculations produced garbage transport
  properties (Pr = 0) and a 500 error. This was found while load-testing the
  new project page.

### 2.5 Smaller bugs noted

| Issue | Status |
|---|---|
| `Ctrl+Shift+Z` redo never fired (`e.key` is `"Z"`). | Not present in revision 2 |
| The pinned list was silently capped at 8. | Not present in revision 2 |
| Constraint text went into `innerHTML` unescaped. | Not present in revision 2 |
| A thermal solver failure returned 200 `{ok:false}`, while a missing regen block returned 400. | Not present in revision 2 |
| The report's Plotly pages were white in dark mode and needed the CDN. | Not present in revision 2 |
| The 3D channel view always showed channel 0. | Not present in revision 2 |
| The envelope mini-chart showed one arbitrary O/F slice. | Not present in revision 2 |
| Off-design defaults disagreed with the schema. | Not present in revision 2 |

## 3. Revision 2

### 3.1 Principles

1. **Answer first.** Every section opens with results computed from sensible
   defaults. Inputs refine them, and results update about 0.35 s after
   typing, with no edit mode, run button or report step.
2. **One design, progressive depth.** Performance → Chamber → Heat load →
   Cooling → Operating range → Trade study → Design sheet. You can jump
   straight to any section; the quick estimate is the same object, so nothing
   is re-typed.
3. **Plain language, engineering units.** Labels say "Chamber pressure",
   "Combustion efficiency", "Heat-transfer factor ×Bartz", with the symbol as
   a secondary hint. Values are shown in mm, bar, kN/N, K and MW/m². Warnings
   are rewritten to name UI controls instead of YAML keys.
4. **Honest numbers.** Uncertainty bands, "showing previous result" markers,
   live-versus-saved results, and energy-balance and fidelity footers are all
   visible.

### 3.2 How each part of the brief is met

| Brief | Revision 2 |
|---|---|
| Simplicity, friendliness | Outcome-first home page (Quick estimate / Heat load / Cooling channels). Four inputs are enough for a first result. Advanced options sit in disclosures. Field hints give typical values. Input problems are listed with friendly field names. Undo/redo, autosave, and number nudging with ↑/↓. |
| Great-looking UI | A flight-ops style design system, dark by default: near-black surfaces, hairline borders, sharp corners, condensed uppercase headings (Barlow Condensed) over Barlow body text, IBM Plex Mono numerals, and one hot and one cool accent that carry meaning (hot gas / coolant). The home page is a compact workspace dashboard (quick tools, recent designs, projects) rather than a landing page. The engine is drawn as a true-scale dimensioned technical drawing, and the design identity sits in a compact title block. A matching light theme is one click away. Chart colours were validated for colour-blind safety; every chart has one axis, hover tooltips and legends. The 3D wall assembly has a hatched cut-away section. |
| Fast results, hand calc → detailed | **Quick estimate** in ~1 s with no project. **Heat load**: a new `resa.models.heatflux` hand calculation (Bartz at an assumed wall temperature) gives peak and total heat and per-propellant absorption capacity in about 10 ms; it lands within 1–13 % of the full solver. **Cooling**: a preview-resolution solve while editing, then full resolution; a **p–h diagram** with saturation dome, isotherms and critical point; a layout assistant that searches for a working first layout. |
| Professional workflow | **Workspace → Project → Engine design → Versions.** Projects are self-contained and export as one file. Designs are complete engine configs; the file store writes them as runnable YAML. The working copy autosaves with optimistic concurrency (409 on conflict). Versions carry a message, author, timestamp and key results. History shows deltas, compare-to-working-copy with friendly diffs, restore and branch. Baseline design, status (Concept → Frozen), and a project table with key results and baseline deltas. |
| Wording | "Engine design" instead of config, "Version" instead of hash, "Check existing hardware" instead of analyze mode, "Nozzle size set by: ideal for ambient / area ratio / exit pressure", "Cooling with: fuel / oxidizer", "Coolant enters at: nozzle end (counter-flow)", and so on. |
| Deployable to Vercel | Static web app plus one Python function; `vercel.json`, `api/index.py`, `requirements.txt`. **NASA CEA backend** (pip wheels, no Fortran) replaces rocketcea wherever it is missing. Storage adapts: a folder locally, PostgreSQL when a database URL is set, otherwise this browser with project files for sharing. The calculation API is stateless and writes nothing to disk. |

### 3.3 Engine and API changes behind it

- **`combustion.backend: cea`** (`resa/properties/nasa_cea.py`). Equilibrium
  uses the NASA CEA rocket solver. Frozen and frozen-at-throat expansion is
  integrated from CEA species thermodynamics, because cea 3.3's own frozen
  solve does not converge. Delivery-temperature enthalpies are shifted with
  CoolProp. Configs that ask for `rocketcea` fall back to it automatically,
  with a warning. Validation against rocketcea 1.2.3 across N2O/ethanol,
  LOX/LH2, GOX/GH2 (delivery states), LOX/CH4 and LOX/RP-1, all three
  nozzle-flow models:

  | Quantity | Max deviation |
  |---|---|
  | c*, Tc, γ, MW, vacuum Isp, pe, Me, ε(pe), μ, Pr | ≤ 0.07 % (RP-1: ≤ 0.4 %, different surrogate data) |
  | Example designs end-to-end (Isp; hottest regen wall) | ≤ 0.03 % Isp; ≤ 0.4 K wall |

- **`cooling:` is optional.** The UI writes only `regen:`, so the duplicate
  concept is gone for new designs; legacy files still load.
- **Thread safety.** rocketcea calls are serialized behind a lock, the NASA
  CEA backend holds its own lock, and calculation endpoints run one at a time
  per process.
- **New endpoints.** `/api/calc/*` (performance, heat flux, cooling with p–h
  data, layout assistant, geometry, export, operating range, trade study,
  YAML) and `/api/workspace/*` (projects, designs, drafts, versions,
  import/export, examples). Covered by `tests/test_calc_api.py`,
  `tests/test_workspace.py` (files, SQLite and PostgreSQL) and
  `tests/test_nasa_cea.py`.

### 3.4 Verification

- The full pytest suite passes, including all existing golden tests.
- An end-to-end browser test covers:
  1. quick estimate
  2. editing and updating results
  3. invalid-input messaging
  4. heat load
  5. saving to a new project
  6. autosave and saving a version
  7. history compare
  8. layout assistant and cooling tabs
  9. operating range
  10. trade study
  11. design sheet
  12. project table
  13. dark theme

  It passes against the file store and in the Vercel-style browser-storage
  mode, with no console errors.
- The Vercel runtime was simulated in a clean virtualenv containing only
  `requirements.txt` and with `VERCEL=1` set. Catalog, performance with the
  CEA fallback, cooling, STL export and example bundles all work there.

## 4. Not in this revision / next steps

- **Accounts and permissions.** The workspace records author names but does
  not authenticate. On Vercel, use Deployment Protection. Proper team roles
  would need an auth provider.
- **Campaigns and full PDF reports in the new UI.** The trade study covers
  one-input sweeps in-app. Multi-config campaigns and PDF report folders
  remain CLI / `/classic/` features. The design sheet prints to PDF from the
  browser.
- **Side-by-side comparison of two designs.** Baseline deltas in the project
  table and version-to-working-copy diffs exist; a dedicated two-design
  overlay chart would be the next step.
- **Unit preferences** (°C, psi, lbf) are not configurable; the UI uses SI
  engineering units throughout.
- **Layout assistant.** It gives a sound first cut but cannot close every
  case. It closes the default quick estimate and typical LOX/ethanol,
  LOX/methane and LOX/hydrogen engines from 2 kN up, but very small engines
  (~500 N) run far above any wall limit at the textbook heat-transfer factor
  of 1.0 — they need film cooling or a calibrated factor, and it says so.
- **STEP export on Vercel.** It needs `cadquery-ocp`, which is too large for a
  function; STL works everywhere.
