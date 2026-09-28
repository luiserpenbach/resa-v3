# RESA Studio

Browser app for rocket engine sizing, heat-load estimates and regenerative
cooling-channel design, on top of the RESA library. Answers come first; the full
configuration grows only as far as a question needs it.

- **Quick estimate** — propellants, thrust, chamber pressure → Isp, flows,
  throat/exit size and peak heat flux in about a second. No project needed.
- **Heat load** — Bartz heat flux along the engine at an assumed wall
  temperature, total heat into the wall, and whether each propellant could
  absorb it.
- **Cooling channels** — full regen solve: wall temperature against the
  material limit, pressure drop, the coolant path on a **p–h diagram**, channel
  cross-sections, 3D wall assembly, stress, STL/STEP export. A layout assistant
  searches for a first layout that works.
- **Projects & versions** — a shared, clearly bounded workspace: projects hold
  engine designs, each with an autosaved working copy and a named version history.

Review of the previous UI and the reasoning behind this revision:
[STUDIO_REVIEW.md](STUDIO_REVIEW.md). Hosting: [DEPLOY.md](DEPLOY.md).

## Run it

```bash
pip install -e ".[studio,report]"        # RESA + API (+ PDF/plot extras for the CLI)
(cd web && npm ci && npm run build)      # the web app -> web/dist
python -m resa_studio                    # http://127.0.0.1:8000
```

Frontend development with hot reload (API proxied to port 8000):

```bash
python -m resa_studio          # terminal 1
cd web && npm run dev          # terminal 2 -> http://localhost:5173
```

The previous interface is still served at **`/classic/`** (file-based configs,
full report folders, campaigns). If `web/dist` is missing, `/` redirects there.
Its paths follow `RESA_PROJECT_ROOT` (repo root), `RESA_OUT_ROOT` (`out/`),
`RESA_CONFIGS_ROOT` (`configs/`) and `RESA_PROJECTS_ROOT` (`configs/projects/`).

## Concepts

| Term | Meaning |
|------|---------|
| **Workspace** | Everything the server (or this browser) stores: a list of projects. |
| **Project** | One engine program, e.g. "Upper stage 2 kN". Self-contained: its designs never reference files outside it. Export/import as a single `.resa-project.json`. |
| **Engine design** | One complete engine configuration (propellants, operating point, chamber, cooling, …). Stored as a plain engine YAML, so `python -m resa run <design>.yaml` runs it directly. |
| **Working copy** | The editable state of a design. Saves automatically (~1 s after an edit); concurrent edits from two people are detected and never silently overwritten. |
| **Version** | A named, permanent snapshot (message, author, time, key results). Compare any version with the working copy, restore it, or branch a new design from it. |
| **Baseline** | One design per project that the others are compared against (coloured deltas in the project table). |
| **Status** | Concept → Preliminary → Detailed → Frozen, set per design. |
| **Quick estimate** | A scratch design kept in this browser; "Save to a project" turns it into an engine design with version 1. |

## A design, section by section

| Section | Inputs | Results |
|---------|--------|---------|
| **Performance** | Size a new engine *or* check existing hardware (throat + measured flows); propellants and delivery conditions; thrust, pressure, mixture ratio (value or best Isp); environment and nozzle expansion; losses; chemistry model | Isp (ambient, vacuum, uncertainty band), flows, throat/exit size, c*, chamber temperature, exit state, Isp under each nozzle-flow model, true-scale outline |
| **Chamber & nozzle** | Contraction ratio, L*, convergent angle, bell/cone, bell length, throat radii, bell angles | Dimensioned drawing, dimension table, 3D view, contour CSV |
| **Heat load** | Assumed hot-wall temperature, heat-transfer factor (± band), film cooling | Heat-flux profile, peak/throat flux, total heat (chamber vs nozzle), recovery temperature, coolant capacity per propellant |
| **Cooling channels** | Coolant side, inlet pressure/temperature, flow direction, feed coupling; channel count; height, rib, wall thickness and spiral angle — constant or varying along the engine (drag points on a mini chart); coverage; wall material and limit; radiation-cooled extension | Hottest wall and margin, band, pressure drop, outlet state, feed margin, coolant Mach, stress ratio; tabs: wall temperature, **coolant & p–h diagram**, channel geometry (cross-section, dimensions, 3D assembly, STL/STEP), stress |
| **Operating range** | Oxidizer-only throttle, mixture-ratio sweep, throttle map | Thrust/Isp curves, throttle-map heatmap with separation cells |
| **Trade study** | One input (pressure, thrust, O/F, area ratio, contraction ratio, L*, coolant pressure/temperature, channel count), range and steps; optional channel solve | One small chart per result, table |
| **Design sheet** | — | Printable one-page summary (Print → PDF) |

Results recompute ~0.35 s after you stop typing. The cooling solve runs at a
fast preview resolution while you edit; switch to **Full resolution** for the
final numbers. Invalid inputs are marked in place and listed above the results,
which keep showing the last valid state.

### Layout assistant

"Find a layout that works" (Cooling channels, before a layout exists):

1. picks a coolant that can carry the heat load without boiling — the fuel if it
   can, otherwise the oxidizer (a propellant with a reachable critical pressure,
   such as N2O, runs supercritical);
2. sizes the channels for coolant speed (30 m/s liquids, Mach 0.15 gases) and
   tapers the height along the nozzle to hold the flow area; picks a copper
   alloy above ~8 MW/m² peak flux; ends the channels at area ratio 15 on large
   nozzles (radiation-cooled beyond);
3. solves variants until the wall stays under its limit with feed margin, or
   returns the best one with a note on what else to change. A wall that runs
   too hot pulls, in order: shallower channels, more (narrower) channels,
   GRCop-42 instead of CuCrZr (1000 K vs 800 K limit), wider ribs; a pressure
   drop beyond the feed budget raises the inlet pressure. The default quick
   estimate (2 kN LOX/ethanol, 20 bar) comes out at ~104 GRCop-42 channels with
   the wall ~30 K under its limit.

## Where projects are stored

| Setup | Storage | Shared? |
|-------|---------|---------|
| Local (`python -m resa_studio`) | `workspace/` folder next to the repo (`RESA_WORKSPACE_DIR` to move it): `<project>/project.yaml`, `designs/<design>.yaml` (runnable engine YAML), `designs/<design>.meta.yaml`, `history/<design>/v0001.yaml` … Deleted items go to `workspace/.trash/`. | Via git — the folder is plain YAML |
| Server with a database | `RESA_WORKSPACE_DB`, `DATABASE_URL` or `POSTGRES_URL` → PostgreSQL (needs `pip install -e ".[workspace-pg]"`) or `sqlite:///path.db` | Yes — everyone on the deployment |
| Hosted without a database (e.g. Vercel, `VERCEL` set) | This browser (localStorage); projects move between browsers as export/import files | No — export to share |

## Keyboard

| Shortcut | Action |
|----------|--------|
| `Ctrl`/`⌘` `Z`, `Shift`+`Z` or `Y` | Undo / redo design edits |
| `Ctrl`/`⌘` `S` | Save a version |
| `↑` / `↓` (+ `Shift`) in a number field | Nudge by one unit of the last decimal (×10) |
| `Esc` | Close dialogs and drawers |

## API

Stateless calculations — every request carries the complete design dict, nothing
touches the disk (so they run serverless too). Invalid designs answer 422 with
`detail = [{path, message}]`.

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/calc/catalog` | Propellant choices, materials, available chemistry, trade-study inputs |
| POST | `/api/calc/validate` | `{ok, errors[{path, message}]}` |
| POST | `/api/calc/performance` | Performance, geometry, contour, propellant states, warnings (off-design sweeps skipped) |
| POST | `/api/calc/heat-flux` | Heat-flux profile + summary + coolant capacity (`wall_temp_K`) |
| POST | `/api/calc/cooling` | Regen solve (`fidelity: preview|full`): summary, profiles, coolant path, p–h dome and isotherms, band, skirt |
| POST | `/api/calc/cooling/suggest` | Layout assistant: regen block + trials + notes |
| POST | `/api/calc/cooling/geometry` | Channel profiles, one cross-section (`x_m`), 3D assembly |
| POST | `/api/calc/cooling/export` | One channel as STL / STEP (STEP needs `cadquery-ocp`) |
| POST | `/api/calc/offdesign` | Throttle / O/F / envelope sweeps |
| POST | `/api/calc/trade-study` | One input over a range → key results per case |
| POST | `/api/calc/yaml/parse`, `/yaml/dump` | Engine YAML ↔ design dict |

Workspace (`/api/workspace/*`): `info`; `projects` (list, create, get, patch,
delete, `export`); `projects/{p}/designs` (create — optionally
`derived_from` — get, patch, delete); `…/draft` (PUT with `revision` → 409 on
conflict); `…/versions` (list, create, get, `restore`); `import`; `examples`
(import the example engines); `examples/bundles` (same, as files, for browser
storage). Contract details: `resa_studio/workspace/routes.py`.

The classic endpoints (`/api/config`, `/api/runs`, `/api/preview`,
`/api/compare`, `/api/campaigns`, `/api/artifacts`) are unchanged and serve `/classic/`.

## Layout

```
web/                    Studio app — Vite + React + TypeScript
  src/lib/              API client, workspace backends, design model, session store
  src/components/       controls, charts (SVG), engine drawing, profile editor, 3D viewer (three.js)
  src/pages/            home, project, design workspace + one file per section
resa_studio/
  api/routes/calc.py    stateless calculations
  adapters/calc_service.py
  workspace/            store interface, FileStore, SqlStore, routes, examples
frontend/public/        classic UI (/classic)
api/index.py            Vercel entrypoint
```

## Tests

```bash
pytest tests/test_calc_api.py tests/test_workspace.py tests/test_nasa_cea.py -q
cd web && npm run typecheck && npm run build
```

`RESA_TEST_PG_URL=postgresql://…` also runs the workspace suite against PostgreSQL.
