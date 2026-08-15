# RESA Studio

Browser UI for editing engine YAML, live geometry previews, fast sizing runs,
full reports, run comparison, and campaigns.

**Layout:** inspector + viewport (see [STUDIO_UI.md](STUDIO_UI.md) for the
design). Geometry and plots occupy the centre stage; config sits in a right
inspector; the sidebar is projects and runs only.

## Install and launch

```bash
pip install -e ".[studio,report]"
python -m resa_studio
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The server serves the
static frontend from `frontend/public/` and the REST API under `/api/`.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESA_PROJECT_ROOT` | auto-detected repo root | Override project root when configs live elsewhere |
| `RESA_OUT_ROOT` | `<root>/out` | Saved report folders |
| `RESA_CONFIGS_ROOT` | `<root>/configs` | Config tree root |
| `RESA_PROJECTS_ROOT` | `<root>/configs/projects` | Project folders for the sidebar |

Preview requests share an in-process cache (48 entries, oldest-entry
eviction, 120 s TTL) so
debounced contour/cooling edits do not re-run the full pipeline on every keystroke.

Optional extras:

| Extra | Purpose |
|-------|---------|
| `studio` | FastAPI + uvicorn (required for the UI) |
| `report` | PDF reports and Plotly plots from full runs |
| `cea` | RocketCEA combustion backend |
| `step` / `cad` | STEP export for regen channel solids |

## Layout

```
┌ RESA   project / config.yaml  ·valid    [Edit] [Run ▾]
├──────────┬──────────────────────────────┬──────────────┤
│ Projects │  Viewport                    │ Inspector    │
│  configs │  Geometry | Thermal | Sweeps │ Design       │
│ Runs     │  Report   | Compare          │ Chamber      │
│          │                              │ Regen        │
│ Campaigns│  KPI strip (Thrust Isp Pc …) │ Off-design   │
└──────────┴──────────────────────────────┴──────────────┘
```

`frontend/public/` is the SPA (no bundler). `resa_studio/` is the FastAPI
app. Live canvases mount in the centre viewport; the inspector is forms only.

## Workflow

1. **Select a project** in the sidebar, then pick a config (or create a project / config with **+**).
2. **Edit** — topbar Edit; changes validate on blur; invalid fields are highlighted per tab.
   Numeric fields nudge with **↑/↓** (one unit of the last decimal place;
   **Shift** for 10×) and live previews follow in the viewport.
3. **Run** (default = fast) — in-memory pipeline, KPI strip + Sweeps charts (no artifacts).
   Full report is in the Run menu — writes `out/<engine>_<hash>/`.
4. **Viewport** — Geometry (chamber 2D/3D or cooling assembly), Thermal (T_wall vs
   limit, linked axial station + section inset), Sweeps, Report (grouped Plotly),
   Compare (shift+click two runs).
5. **Saved runs** — compact list (label, age, warnings). Hover for Pin / Name.
   Shift+click to pick compare A/B, then open the Compare viewport.
6. **Pin a baseline** — other runs' KPIs show **delta chips** vs the baseline
   (green = favorable, red = unfavorable).
7. **Campaigns** — sidebar footer; run multi-config batches from `campaigns/*.yaml`.

**Ctrl/Cmd+Enter** runs fast. Collapse the nav or inspector from the topbar
to give the viewport the full window.

## Inspector tabs

| Tab | Features |
|-----|----------|
| Design | Operating point, expansion mode (ε / pe / optimum) |
| Analyze | Fixed geometry + test mass flows |
| Chamber | Contour & sizing; 2D/3D in the Geometry viewport |
| Regen | Channel layout, axial profiles, sync matrix. Assembly 3D (wall / channels / closeout + cutaway) and STL/STEP in Geometry; thermal margin plot in Thermal |
| Off-design | Sweep toggles; charts in the Sweeps viewport after run |

Draft edits are auto-saved to localStorage per config path. Undo/redo works
while editing.

## API overview

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Server status |
| GET | `/api/config/list` | Config tree |
| GET | `/api/config/schema` | JSON Schema for the editor |
| GET | `/api/config/resolve` | Load + compose config |
| POST | `/api/config/validate` | Validate inline dict |
| GET | `/api/projects/list` | All projects with nested configs |
| POST | `/api/projects/create` | New project folder + `<slug>.yaml` starter config |
| POST | `/api/projects/{slug}/configs` | New config in a project |
| POST | `/api/config/save` | Save edits to the file being edited (diffed against the `base:` config and fragment refs preserved when set). Send `expected_file_sha256` from `/resolve` to reject concurrent overwrites (HTTP 409). |
| POST | `/api/runs/fast` | Fast pipeline (no disk write) |
| POST | `/api/runs/full` | Full report folder |
| GET | `/api/runs` | List saved runs (KPIs, labels, baseline flag) |
| GET | `/api/runs/{engine}/{hash}` | Open saved run |
| POST | `/api/runs/{engine}/{hash}/meta` | Set run label / note |
| GET/POST | `/api/runs/baseline` | Get / pin / clear the comparison baseline |
| POST | `/api/preview/contour` | Live contour (cached pipeline) |
| POST | `/api/preview/cooling/*` | Section, 3D, export, suggest channels |
| POST | `/api/preview/regen/thermal` | Reduced-station regen thermal preview |
| POST | `/api/compare/runs` | Diff two saved runs |
| POST | `/api/compare/configs` | Diff two config dicts |
| GET | `/api/campaigns/list` | Campaign YAML index |
| POST | `/api/campaigns/run` | Execute a campaign YAML under `campaigns/` (writes to `out/<campaign-output>/`, not the shared run root) |
| GET | `/api/artifacts/{engine}/{hash}/{path}` | Serve report file |

## Tests

Studio API tests live in `tests/test_studio_api.py`. CI installs the `studio`
extra so these run on every push:

```bash
pip install -e ".[dev,studio,plot,pdf]"
pytest tests/test_studio_api.py -q
```

## See also

- [CONFIGURATION.md](CONFIGURATION.md) — YAML field reference
- [../README.md](../README.md) — CLI, campaigns, library layout
