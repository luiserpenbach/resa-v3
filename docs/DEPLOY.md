# Deploying RESA Studio

Three ways to run the Studio, from a laptop to a shared team deployment.

| | Local | Vercel | Any container host |
|---|---|---|---|
| Web app | served by FastAPI from `web/dist` | Vercel CDN (`web/dist`) | served by FastAPI |
| API | `python -m resa_studio` | one Python function (`api/index.py`) | `uvicorn resa_studio.api.main:app` |
| Projects | `workspace/` folder (git-friendly YAML) | this browser, or PostgreSQL | folder or database |
| Chemistry | rocketcea if installed, else NASA CEA | NASA CEA | NASA CEA (or rocketcea) |
| Classic UI, report folders, campaigns | yes | no (read-only filesystem) | yes, with a writable disk |

## Local

```bash
pip install -e ".[studio,report]"
(cd web && npm ci && npm run build)
python -m resa_studio            # http://127.0.0.1:8000
```

Projects land in `./workspace/` (override with `RESA_WORKSPACE_DIR`). The folder
is plain YAML — commit it to a repository to share a project workspace with a
team and get git history on top of the in-app versions.

## Vercel

The repository is ready to import as a Vercel project:

- `vercel.json` builds the web app (`cd web && npm ci && npm run build`, output
  `web/dist`) and routes `/api/*` to the Python function `api/index.py`, which
  exports the FastAPI app. Every other path falls back to `index.html`.
- `requirements.txt` holds the function's runtime dependencies. It contains no
  plotting or PDF libraries, which keeps the bundle at about 410 MB unpacked.
  The largest are scipy, pandas, numpy and CoolProp.
- `.python-version` pins Python 3.12. NASA CEA needs Python ≥ 3.11 and ships
  manylinux wheels, so no compiler is needed.
- The function allows 60 s and 2 GB. A full cooling solve takes 0.5–5 s, the
  layout assistant 5–15 s, and a throttle map up to ~15 s.

### Storage on Vercel

- **No database (default).** The server reports `storage: "none"` and the app
  keeps projects in the user's browser. People share a project by exporting it
  (project ⋯ → *Export project file*) and importing it on the home page. The
  example projects load from the server in this mode too.
- **Shared team workspace.** Add a PostgreSQL database, for example Neon from
  the Vercel Marketplace. It sets `DATABASE_URL` / `POSTGRES_URL`, and the store
  creates its tables (`resa_projects`, `resa_designs`, `resa_versions`) on
  first use. `psycopg[binary]` is already in `requirements.txt`.

### Access control

The Studio has no user accounts. Authors are the names people enter under
*Preferences*. On a public deployment, turn on Vercel **Deployment Protection**
(password or Vercel Authentication) so only your team reaches the workspace
and the calculation API.

### Limits to know

- The calculation endpoints handle one request at a time per instance. The
  CEA and CoolProp native libraries keep global state and are not thread-safe;
  Vercel scales out instances instead.
- STEP export needs `cadquery-ocp`, which is too large for a function. STL
  export works.
- Full report folders (PDF, Plotly HTML) and campaigns need a writable disk.
  They stay available in local and container setups via the CLI and `/classic/`.

## Container / VM

```bash
pip install -e ".[studio,workspace-pg]"
(cd web && npm ci && npm run build)
DATABASE_URL=postgresql://user:pass@host/db \
  uvicorn resa_studio.api.main:app --host 0.0.0.0 --port 8000
```

Without `DATABASE_URL` the workspace lives in `RESA_WORKSPACE_DIR` (default
`./workspace`); mount it on a persistent volume. For PostgreSQL, run the
workspace tests once against a scratch database:

```bash
RESA_TEST_PG_URL=postgresql://postgres@127.0.0.1:5432/resa_test pytest tests/test_workspace.py
```

## Environment variables

| Variable | Effect |
|----------|--------|
| `RESA_WORKSPACE_DB` / `DATABASE_URL` / `POSTGRES_URL` | Database workspace (`postgresql://…`, `postgres://…` or `sqlite:///path.db`), first one set wins |
| `RESA_WORKSPACE_DIR` | Folder workspace location (default `<repo>/workspace`) |
| `VERCEL` | Set by Vercel. Without a database URL, projects are stored in the browser |
| `RESA_WORKSPACE_EXAMPLES_DIR` | Where example projects are read from (default `configs/projects`) |
| `RESA_WEB_DIST` | Built web app to serve (default `web/dist`) |
| `RESA_PROJECT_ROOT`, `RESA_OUT_ROOT`, … | Classic UI paths, see [STUDIO.md](STUDIO.md) |
