# AGENTS.md

## Cursor Cloud specific instructions

RESA is a **pure-Python** project (Python ≥3.10; this VM has 3.12). It contains two
products sharing one core library:

- **RESA** — rocket-engine sizing/analysis CLI + Python API (`python -m resa ...`). Core product.
- **RESA Studio** — optional FastAPI web UI (`python -m resa_studio`) that serves a
  vanilla-JS SPA from `frontend/public/` and wraps the same library. No bundler / no `package.json`.

There is **no database, cache, queue, or Docker** — everything runs locally and is file-based
(YAML configs in, `out/<engine>_<hash>/` report folders out). `out/` is git-ignored.

### Environment

- Dependencies live in a **virtualenv at `.venv/`** (the startup update script keeps it in sync).
  Always `source .venv/bin/activate` before running anything.
- Standard install/test/run commands are documented in `README.md` and `.github/workflows/ci.yml`;
  prefer those as the source of truth.

### Combustion backend gotcha (non-obvious)

Configs pick a combustion backend via `combustion.backend`:

- `table` — offline CEA tables. **This is the default supported path** used by CI and the golden
  test suite (`configs/ci/*.yaml`). Works with the base install; no extra system deps.
- `rocketcea` — the `rocketcea` package (needs a system Fortran toolchain: `gfortran` +
  `python3-dev`). The **README's headline examples** (`configs/projects/*/design.yaml`) use this
  backend, so they fail with `ModuleNotFoundError: rocketcea` unless `rocketcea` is installed.

`rocketcea` and `cadquery-ocp` (STEP/CAD export, `tests/test_step_export.py`) are **optional
enhancers**. They are pre-installed in the snapshot `.venv` but are intentionally **not** in the
startup update script (they need system Fortran/dev headers and heavy binary wheels). If a future
`.venv` is missing them, reinstall with: `pip install rocketcea cadquery-ocp` (first ensure
`gfortran` and `python3.12-dev` are apt-installed for `rocketcea`).

### Lint / test / build / run

- **Lint:** none configured (no ruff/flake8/black/mypy config in the repo; CI runs no linter).
- **Test:** `pytest tests/` (full suite). CI splits STEP-export tests into a separate job:
  `pytest tests/ -q --ignore=tests/test_step_export.py`, then
  `pytest tests/test_step_export.py tests/test_channel_export.py -q`.
- **Build:** editable install only — `pip install -e ".[dev,plot,pdf,studio]"` (no separate build step).
- **Run (CLI):** `python -m resa run configs/ci/e2_c1_design.yaml` (table backend, always works)
  or `python -m resa report <config>` to write a full report folder under `out/`.
- **Run (Studio):** `python -m resa_studio` → serves API + UI at http://127.0.0.1:8000.
  Health check: `GET /api/health`. Trigger an analysis with `POST /api/runs/fast`
  (`{"config_path": "configs/ci/e2_c1_design.yaml"}`). The full API is under `/api/*`
  (see `/openapi.json`).
