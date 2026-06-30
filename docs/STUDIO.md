# RESA Studio

Browser UI for editing engine YAML, live geometry previews, fast sizing runs,
full reports, run comparison, and campaigns.

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

Preview requests share an in-process LRU cache (48 entries, 120 s TTL) so
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
frontend/public/     SPA (no bundler)
resa_studio/         FastAPI app + adapters
  api/routes/        REST endpoints
  adapters/          config, run, preview, compare, campaign services
```

## Workflow

1. **Select a project** in the sidebar, then pick a config (or create a project / config with **+**).
2. **Edit** — changes validate on blur; invalid fields are highlighted per tab.
3. **Run fast** — in-memory pipeline, KPIs + off-design mini charts (no artifacts).
4. **Full report** — writes `out/<engine>_<hash>/` with plots, PDF, CSV, regen
   artifacts when configured.
5. **Saved runs** — open prior report folders; shift+click to pick compare A/B.
6. **Campaigns** — run multi-config batches from `campaigns/*.yaml`.

## Design workspace tabs

| Tab | Features |
|-----|----------|
| Design | Operating point, expansion mode (ε / pe / optimum) |
| Analyze | Fixed geometry + test mass flows; contour preview |
| Chamber | Contour & sizing with live 2D/3D preview |
| Cooling | Channel layout, thermal KPIs, STL/STEP export |
| Regen | Profile editors, sync matrix, thermal sparkline |
| Off-design | Structured sweep toggles; charts in Results after run |

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
| POST | `/api/projects/create` | New project folder + `design.yaml` |
| POST | `/api/projects/{slug}/configs` | New config in a project |
| POST | `/api/config/save` | Save edits to the file being edited (thin overlay when `base:` is set) |
| POST | `/api/runs/fast` | Fast pipeline (no disk write) |
| POST | `/api/runs/full` | Full report folder |
| GET | `/api/runs` | List saved runs |
| GET | `/api/runs/{engine}/{hash}` | Open saved run |
| POST | `/api/preview/contour` | Live contour (cached pipeline) |
| POST | `/api/preview/cooling/*` | Section, 3D, export, suggest channels |
| POST | `/api/preview/regen/thermal` | Reduced-station regen thermal preview |
| POST | `/api/compare/runs` | Diff two saved runs |
| POST | `/api/compare/configs` | Diff two config dicts |
| GET | `/api/campaigns/list` | Campaign YAML index |
| POST | `/api/campaigns/run` | Execute a campaign |
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
