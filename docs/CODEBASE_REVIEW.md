# RESA v3 — Codebase Analysis & Review

Deep review of bugs, workflow errors, unused code, and feature effectiveness,
covering the core physics (`resa/models`, `resa/properties`, `resa/pipeline.py`),
regen cooling (`resa/regen`, `resa/regen_channels`), config/campaign/reporting
(`resa/config`, `resa/campaign.py`, `resa/reporting`), the Studio backend
(`resa_studio/`), and the Studio frontend (`frontend/public/`).

Findings marked **[verified]** were confirmed by executing code or tests, not
just by reading. Test-suite state at time of review: **2 failed, 81 passed,
4 skipped** (`pip install -e ".[report,dev,studio]"`, Python 3.11).

---

## 1. Executive summary

The core engineering is genuinely good: the single-kernel design
(`evaluate_point` shared by sizing, analyze mode, and off-design sweeps) is
real and quantitatively verified consistent; the gas dynamics, thrust
coefficient, O/F optimization, and rocketcea unit conversions all check out;
the regen heat-transfer correlations (Bartz, Gnielinski, Churchill, Jackson,
Chen, fin efficiency) are transcribed correctly and the marching solver is
numerically robust; YAML inheritance + file references compose correctly for
all 17 shipped configs; campaigns, reports, and diffs run end-to-end.

The problems cluster in four themes:

1. **Silent-wrong-results bugs** — the most dangerous class for an engineering
   tool: a transposed PDF envelope heatmap, a coolant mass-flow path that
   ignores `coolant_side` (up to ~4× flow error), a curvature-correlation
   convention error (~1.7× HTC enhancement bias), an "energy closure"
   diagnostic that is identically zero, and contour generation that silently
   self-intersects at contraction ratios ≲ 3.5.
2. **The last bug-fix commit is half-landed** — `07c3b59` fixed the Studio
   save logic but committed the already-destroyed `E2-1A/design.yaml`, so its
   own regression test fails, the E2-1A fragment files are orphaned, and two
   further data-loss bugs remain in overlay saving.
3. **Config-validation gaps** — a validator early-return lets known-bad regen
   configs through; the regen schema silently ignores unknown keys (typos)
   while the engine schema rejects them; docs promise strictness that doesn't
   hold.
4. **Frontend polish debt** — canvas previews illegible in the default dark
   theme, a dead-end "edit run snapshot" flow, systemic `innerHTML` XSS, and
   listener/GPU-buffer leaks, plus a large amount of orphaned code from an
   incomplete regen-editor migration.

---

## 2. Reproducible failures (run locally)

### F1. `tests/test_studio_api.py::test_save_preserves_yaml_file_refs` FAILS — the fix commit shipped the broken fixture **[verified]**

Commit `07c3b59` ("Fix Studio save destroying E2-1A config file references")
added `_preserve_file_refs` (`resa_studio/adapters/config_service.py:54`) and a
regression test — but committed the already-flattened
`configs/projects/E2-1A/design.yaml` (all fragment refs inlined, comments
lost) instead of restoring the original. Consequences:

- The regression test fails on a clean checkout. Restoring the pre-fix
  `design.yaml` (from `ab908bd`) makes the test **pass** — the code fix itself
  works; only the fixture is wrong.
- `prop_n2o_ethanol.yaml`, `chamber_E2_TC_01.yaml`, `cooling_none.yaml` in the
  E2-1A project are now referenced by **nothing**, and the inlined values have
  drifted from the fragments (`eta_cstar` 0.92→0.93, `eta_cstar_tol`
  0.05→0.03; `contour: rao_bell` vs the TC-01 fragment's conical 59°).
- `project.yaml` claims "TC-01 conical chamber"; the config runs a Rao bell.
- `campaigns/E2-1A/e2_1a.yaml` is titled "(no regen)" and `cooling_none.yaml`
  says "E2-1A has no active regen cooling", yet all three configs inherit a
  full `regen:` block with `solver.enabled: true`.

**Fix:** restore the file-ref version of `design.yaml` (re-pointing refs, and
folding the intended value changes into the fragments or the overlay), or
update the fixture/test/docs to the new intent — but pick one story.

### F2. `tests/test_pdf_report.py::test_pdf_report_generated` FAILS in the documented dev setup **[verified]**

The test loads `configs/projects/e2_c1/design_regen.yaml`, whose base uses
`backend: rocketcea`, with no `pytest.importorskip("rocketcea")`. rocketcea
needs a Fortran toolchain and is not in the `[report,dev]` extras the README
tells contributors to install, so the suite is red out of the box. Every other
optional dependency is guarded (`OCP`, `plotly`, `CoolProp`, `matplotlib`).
**Fix:** point the test at a `configs/ci/` table-backend config (better — PDF
generation then actually runs offline) or add the importorskip.

---

## 3. High-severity findings

### Silent wrong results (core & regen)

- **Contour self-intersects at moderate contraction ratios** —
  `resa/models/contour.py:94-97`. `dx_cone = (rB − rA1)/tan(β)` goes negative
  whenever `rA1 = Rt + R1(1−cos β)` exceeds `rB`; with schema defaults this
  happens for CR ≲ 3.5 **[verified: CR 2.5 → non-monotonic x, negative
  frustum volume corrupting the L*-derived cylinder length]**. No guard or
  warning anywhere; shipped configs (CR 7–15) just avoid the region. Small
  engines with CR 2–4 are common. **Fix:** feasibility check that raises with
  the offending geometry.

- **Standalone regen path ignores `coolant_side`** —
  `resa/regen_channels/solver.py:53-57`. When `mdot_total` is absent and
  `mdot_from_engine` is true, the coolant fraction is hardcoded to the
  *oxidizer* fraction `of/(1+of)`. Only `resa/regen/integration.py:90-93`
  honors `coolant_side`. A standalone fuel-cooled config at O/F 4 gets ~4×
  too much coolant flow — walls report far cooler than reality.

- **"Energy closure" diagnostic is a tautology** —
  `resa/regen_channels/solver.py:195`, `scripts/diagnose_regen_energy.py:46`,
  `viz.py:262`. `mdot_total·Δh − Q_total ≡ 0` by construction (Δh is computed
  *from* Q) **[verified: prints exactly 0.0]**. The dedicated diagnostic
  script can never detect an energy bug. **Fix:** compare against an
  independent hot-gas-side integral.

- **Curvature ratio convention error (helical channels)** —
  `resa/regen_channels/layout.py:88-92` + `solver.py:135` pass `Dh/R_curve`
  (d over *radius*) where Ito friction and the Schmidt HTC factor
  (`correlations.py:20,30`) expect d over coil *diameter*. The Schmidt
  enhancement term is overestimated ~1.74×, biasing helical-channel HTC
  optimistic — the wrong direction for a thermal-margin tool.

- **PDF envelope heatmap is transposed** — `resa/reporting/pdf_plots.py:120-125`.
  `imshow(z.T)` with `z` shaped `(n_of, n_throttle)` maps throttle onto the
  O/F axis and vice versa; the Pc contour overlay in the *same axes* uses the
  correct orientation, so heatmap and contours disagree, and the PDF
  contradicts the (correct) interactive Plotly version in the same report
  folder. Masked because all shipped grids are square (`n: [22,22]`).

### Data loss (Studio config saving)

- **Explicit-`null` keys stomp user edits on overlay save** —
  `resa_studio/adapters/config_service.py:93-97`. `_build_save_payload`
  re-applies `overlay[key] = None` for every key that was `null` on disk
  *after* diffing, discarding the user's new value **[verified: editing
  `operating_point: null` (the exact shape of `E2-1A/asbuilt.yaml`) to a real
  block saves back as `null`; API returns 200 OK]**.

- **Overlay save still drops fragment refs when content equals the inherited
  value** — `config_service.py:99-109`. The "drop inherited-equal branches"
  loop deletes the ref `_preserve_file_refs` just restored **[verified: a
  no-op save of `base:` + `chamber: chamber_frag.yaml` loses the `chamber:`
  line]** — the same bug class commit `07c3b59` targeted.

- Related, lower grade: saves rewrite via `yaml.safe_dump`, destroying all
  hand-written comments (e.g. calibration notes in `asbuilt.yaml`), and there
  is no concurrency guard (last-write-wins between two tabs)
  (`config_service.py:195-198`).

### Broken workflow (Studio)

- **Editing a saved run's snapshot is a dead end, advertised as working** —
  backend `config_service.py:146-149` marks `out/**/config_resolved.yaml`
  `writable: true` (UI enables Edit and hints "Save updates the run
  snapshot"), but `save_config` (`:186-191`) rejects everything outside
  `configs/projects/`; the frontend guard (`frontend/public/app.js:353-360`
  vs `app.js:864` setting `activeConfig = null`) independently blocks it with
  a confusing error. User edits are lost on cancel/navigation.

### Frontend

- **Canvas previews illegible in default dark theme** —
  `frontend/public/workspace-preview.js:309-367, 673-764, 1206-1228`,
  `studio-p2.js:14,46`. `ctx.strokeStyle = "var(--accent)"` is invalid for
  Canvas 2D and silently falls back to black — on the `#0f1014` dark
  background, the contour line, section channels, axis text, and off-design
  sweep charts are effectively invisible. The newer
  `AxialProfileEditor._canvasColors()` (`regen-design.js:308-317`) resolves
  vars correctly via `getComputedStyle`; the older canvases were never
  migrated.

- **Stored XSS via `innerHTML`** — `app.js:910-916` interpolates the free-text
  project name into `innerHTML` (persisted server-side; executes for anyone
  opening Studio), with the same pattern for engine names, KPI/warning text,
  compare outdirs, campaign names, and diff tables (`app.js:501-513, 524-527,
  674-677, 764-780, 796-799`, `studio-p2.js:184-187`,
  `config-editor.js:1078-1080`). Combined with `allow_origins=["*"]` CORS on
  an unauthenticated file-writing API (`resa_studio/api/main.py:21-27`), a
  drive-by web page can write configs on 127.0.0.1:8000. Local-tool context
  bounds the impact, but both halves are cheap to fix (escape/`textContent`;
  drop wildcard CORS).

---

## 4. Medium-severity findings

**Validation gaps**

- `resa/regen_channels/config.py:195-209` — `_sync_compat`'s legacy branch
  `return`s a `model_copy` early, skipping the `mdot_total`-required and
  `from_engine`/`sync.contour` checks **[verified: a config the error message
  says must be rejected validates cleanly]**, then fails deep in the solver.
- Regen schema models are plain `BaseModel` (no `extra="forbid"`), so typos
  (`heigth:`) silently fall back to defaults **[verified]** — contradicting
  `docs/CONFIGURATION.md:7` ("Unknown keys are rejected") and the strict
  engine schema.
- `resa/config/schema.py:49-61` — `CombustionTable` doesn't include `of` in
  the shape check: a list `of` with scalar properties validates, then crashes
  at run time inside `np.interp` **[verified]**.
- `resa/models/offdesign.py:73-89` — sweep-range "clipping" (`lo=max, hi=min`)
  yields `lo > hi` when the requested range is disjoint from the combustion
  table → descending out-of-table sweep → mid-run crash instead of a clean
  config error.

**Correctness / consistency**

- `resa/config/schema.py:195` — `chamber.n_stations` is validated, documented
  (`CONFIGURATION.md:241`), printed in the PDF, and set by shipped configs,
  but `contour.generate` hardcodes its point counts; the knob does nothing.
- `resa/pipeline.py:83-103` + `resa/results.py:138-144` — design-mode
  uncertainty band mixes re-*sized* geometry (tc bounds) with fixed-geometry
  off-design bounds; only the analyze-mode band is self-consistent.
- `resa/regen_channels/viz.py:249-265, 90-92` — plotly reassigns
  `yaxis="y4"` traces to `y2` in subplots **[verified]**: coolant pressure
  (~60 bar) is drawn on the temperature axis; the configured right-hand
  "p [bar]" axis never receives a trace; wrap-angle squashes the beta curve.
- `resa/regen_channels/diff.py:134-135` — reads attr `inlet_at_nozzle` that no
  code sets (solver stores `coolant_inlet_location`), so for
  `injector_end`-inlet configs the diff reports the *inlet* quality as
  "outlet quality".
- `resa/campaign.py:73` + `resa/__main__.py:38` — rollup CSV columns built
  from a `set` → nondeterministic order **[verified: two consecutive runs
  differ]**; breaks CSV diffs.
- `configs/projects/ex15/regen.yaml:60` — `coolant_fraction: 0.153846`
  (1/6.5) vs `design.yaml`'s `of_ratio: 5` (fuel fraction 1/6): the solver
  gets ~8% less coolant than the engine's fuel flow, biasing walls hot.
- `resa/regen_channels/export.py:68-75` — STEP export catches only
  `ImportError`; OCC `RuntimeError`s (sewing/loft/cap failures) abort the
  whole report *after* a successful solve.
- `resa_studio/adapters/preview_cache.py:43-82` — entries are timestamped at
  request *start*: any pipeline slower than the 120 s TTL is expired on
  arrival (no cache hits ever), and waiters that wake without a fresh entry
  all become concurrent duplicate leaders — a thundering herd on exactly the
  slow configs the cache exists for. Also FIFO, not the documented LRU.
- `resa_studio/adapters/campaign_service.py:42-62` — no repo-root confinement
  on campaign paths; reports the shared `out/` root (up to 200 historical
  files of *other* runs) as this campaign's artifacts; outside-repo path →
  unhandled ValueError → 500 *after* the campaign already ran.
- `resa_studio/settings.py:31-33` — the documented `RESA_OUT_ROOT` /
  `RESA_PROJECTS_ROOT` env overrides break every service that calls
  `path.relative_to(repo_root)` when pointed outside the repo (→ 500s).
- `resa/config/loader.py:43-47` — a child's file ref is resolved *before* the
  base merge, so refs deep-**merge over** the base block instead of splicing
  in whole (docstring and docs say "spliced in"). CI configs work only
  because the CEA fragments happen to override `backend:`. Load-bearing,
  undocumented semantics.
- Frontend: `app.js:630-646` — `data.artifacts` is always truthy (`[]`), so
  the fast-run rendering branch is dead: wrong plot-source stamp, wrong
  sidebar highlight, wrong empty-state message. `studio-p2.js:89-99` — the
  envelope mini-chart feeds a 2-D grid into a 1-D chart → NaN → blank chart.
  Window-listener + ResizeObserver leaks on every editor re-render
  (`workspace-preview.js:115-116, 518-524, 982-990`, `regen-design.js:558`),
  a per-frame `gl.createBuffer()` leak (`workspace-preview.js:611-618`), and
  a preview-overlay ref-count leak on aborted requests
  (`workspace-preview.js:1150-1169, 1332-1413`) that leaves the spinner stuck.

**Docs drift**

- `docs/CONFIGURATION.md:14-37, 59, 605-614` and the CLI docstring
  (`resa/__main__.py:3-6`) reference pre-reorganization paths
  (`configs/e2_c1/...`) that no longer exist.
- `CONFIGURATION.md:236` documents `conv_half_angle_deg` default 30; the
  schema default is 40 (`schema.py:189`). EX15 is described as ε = 50 in two
  places; `design.yaml` sets `eps: 20`.
- `docs/STUDIO.md`: claims a thin-overlay save feature whose flag is
  hard-coded `False` (`config_service.py:206`), a separate "Regen" tab that is
  merged into Cooling, and `design.yaml` creation where `{slug}.yaml` is
  actually written (`project_service.py:205`).

---

## 5. Low-severity findings

- `resa/config/loader.py:41-43` — empty YAML file → `AttributeError` on
  `None.pop` **[verified]** (`read_raw_config` guards this; `_load_raw`
  doesn't).
- `resa/campaign.py:65,113,149-150` — `spec.output` resolved against CWD
  (unlike every other campaign path); folder-diff output paths get no parent
  mkdir (regen-diff path does) and no traversal guard; `write_report` embeds
  the raw engine string in the folder name (`report.py:206`).
- `resa/reporting/pdf_report.py:333-367` — warning/YAML text goes into
  reportlab `Paragraph` unescaped; a `<b>`-like token raises and kills the
  campaign after most artifacts are written **[verified]**.
- `resa/models/offdesign.py:21-30` — per-point `pc_converged` dropped by
  `_collect`; unconverged sweep points are indistinguishable.
- `resa/models/contour.py:137-150` — no check that bell length exceeds the
  throat-arc end (eps ≈ 1.1 folds the divergent contour back silently).
- `resa/models/thrust_chamber.py:85-153` — `eta_cf` multiplies the whole CF
  including the negative ambient term, slightly *overestimating* sea-level
  thrust; convention worth documenting.
- `resa/results.py:78-80` — bare `assert` shape validation (disabled under
  `python -O`).
- `resa/regen_channels/layout.py:42` — `np.gradient` endpoint cells
  overestimate total area/Q/Δp by n/(n−1); `:49-52` dict-form helix profiles
  ignore `helix.interp`; `:62-74` no guard at β = 90°.
- Studio: prefix containment checks without a trailing separator
  (`config_service.py:136`, `artifacts.py:19` — `../` between sibling run
  dirs); preview routes map all server crashes to 400 (`preview.py:43-44`);
  `GET /api/projects/{slug}` 500s on invalid slugs; project-create TOCTOU;
  fragment YAMLs listed as openable configs that 422 (`project_service.py:62-76`);
  predictable shared temp filename for channel STL export
  (`preview_service.py:204`).
- `.gitignore` drift: current campaign outputs (`ci_golden_output/`,
  `e2_1a_output/`, `e2_c1_output/`, `e2_c1_output_regen/`) are not ignored,
  while stale `e2_output/`, `e2_output_regen/` entries remain.
- Frontend: `constraint-fail` class has no CSS rule (`.constraint-error` is
  styled); tuple inputs write NaN→`null` transiently while a field is cleared;
  shift-click compare can select the same run twice; one failed
  `/api/health` aborts init with no retry.

### Unused / dead code inventory

| Location | Item |
|---|---|
| `resa/models/gasdynamics.py:44` | `temperature_ratio_from_mach` — no callers |
| `resa/properties/fluids.py:56-67` | `transport()`, `cache_info()` — regen uses its own |
| `resa/models/thrust_chamber.py:93` | `"comb"` key in `evaluate_point` result — never consumed |
| `resa/config/schema.py:220,223` | `cooling.mdot_coolant_kg_s`, `cooling.correlation` — validated, documented, never read |
| `resa/regen_channels/config.py:139` | `SolverCfg.max_iter_wall` — solver hardcodes 200 |
| `resa/regen_channels/correlations.py:30` | `curvature_htc_factor(Re, …)` — `Re` param unused |
| `resa/regen_channels/contour.py:49`, `layout.py:40`, `coolant.py:47-48`, `profiles.py:65` | `Contour.area`, `phi_wall`, unreachable N2O alias clause, `is_constant` |
| `scripts/extract_config_editor.py` | 0-byte file since initial commit |
| `resa/campaign.py:6`, `resa/reporting/plots.py:7`, `pdf_plots.py:12` | unused `field` / `numpy` imports, unused `_FONT` |
| `resa_studio` | `GET /config/list` (self-described "legacy"), `POST /config/validate/path`, `POST /compare/configs`, artifacts-list, cache-stats — unused by frontend; vestigial always-false `created_override` / `is_override` fields still plumbed through UI |
| `frontend/public` | `renderConfigNav`, unreachable "Restart Studio" branch (`app.js`); dead classes `ProfilePlotCanvas`, `ProfileBreakpointSliders`, matrix helpers, `regenProfilePoints` etc. (`workspace-preview.js:167-265, 776-965`); `buildProfileField` (`regen-editor.js:42-173`) + its "legacy" CSS block (`styles.css:1422-1458`); unreachable editor section paths (`config-editor.js:705-744`); several orphaned CSS selectors |

The frontend dead code is concentrated around a half-finished migration from
the legacy regen profile editor to `AxialProfileEditor` — worth deleting in
one sweep.

---

## 6. Feature effectiveness

| Feature | Verdict |
|---|---|
| Design-mode sizing | **Works, verified.** `size()` output round-trips exactly through `evaluate_point`; optimum expansion returns exactly `pe = p_amb`; max-Isp O/F search matched a 401-point brute-force scan. |
| Analyze mode | **Works.** Uncertainty band self-consistent (unlike design mode's, §4). |
| Off-design sweeps | **Works** within table bounds; disjoint ranges crash mid-run (§4). |
| YAML config system | **Works, verified** across 3-deep `base:` chains, null-clearing, cross-directory refs — but ref-over-base is merge-not-splice (§4) and Studio saving can destroy structure (§3). |
| Campaigns / rollups / diffs | **Work end-to-end** (`ci_golden` verified). Rollup column order nondeterministic. |
| HTML/PDF reports | **Work**, but the PDF envelope heatmap is transposed and PDF/HTML contradict each other (§3). |
| Regen solver | **Works end-to-end** (smoke run: plausible T_wall/Δp, boiling regime detected); correlations correct. Biases: coolant_side ignored standalone, curvature convention, EX15 coolant fraction — all optimistic. The energy-closure diagnostic validates nothing. |
| STL/CSV/centerline exports | **Consistent with solved data** (units/ordering verified). STEP failure handling fragile. |
| Studio: previews, fast/full runs, compare, campaigns | **Work end-to-end**; API layer accurately matches routes. Cache defeats itself for slow configs; canvas previews illegible in dark mode; envelope mini-chart blank. |
| Studio: config editing/saving | **The weak spot.** Three verified data-loss modes (ref inlining fixture, explicit-null stomping, inherited-equal ref dropping), comment destruction, run-snapshot editing dead end. |
| Test suite | Good golden coverage of physics; 2 failures (§2); no tests for the contour low-CR regime, PDF plot orientation, or overlay-save edge cases — exactly where the bugs are. |

---

## 7. Recommended priorities

1. Restore `configs/projects/E2-1A/design.yaml` file refs (or re-scope the
   test) so the suite is green, and reconcile the E2-1A project's
   regen/no-regen contradiction (§2 F1, §3).
2. Fix the two remaining overlay-save data-loss bugs in
   `_build_save_payload` and stop advertising run-snapshot editing as
   writable (§3).
3. Add the convergent-geometry feasibility guard in `contour.py` and honor or
   remove `chamber.n_stations` (§3, §4).
4. Fix the regen quantitative biases: `coolant_side` in the standalone path,
   the d/D curvature convention, the EX15 coolant fraction, and replace the
   tautological energy-closure diagnostic (§3).
5. Transpose fix in `pdf_plots.envelope_figure` + a non-square-grid test (§3).
6. Frontend: resolve CSS vars for canvas colors (pattern already exists in
   `regen-design.js`), escape all `innerHTML` interpolations, drop wildcard
   CORS (§3).
7. Make the regen schema strict (`extra="forbid"`), fix the `_sync_compat`
   early return, and unguard the pdf test / fix `.gitignore` and docs paths
   (§2 F2, §4).
8. Delete the dead code inventory (§5), especially the legacy regen editor
   remnants.
