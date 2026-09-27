"""RESA Studio FastAPI application."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from resa_studio import __version__
from resa_studio.api.routes import artifacts, calc, campaigns, compare, configs, preview, projects, runs
from resa_studio.settings import FRONTEND_DIR, REPO_ROOT, WEB_DIST
from resa_studio.workspace.routes import router as workspace_router

app = FastAPI(
    title="RESA Studio",
    description="UI API for Rocket Engine Sizing & Analysis",
    version=__version__,
)

# The frontend is served same-origin by this app; CORS exists only for a
# separate localhost dev server. A wildcard would let any web page the user
# visits call the file-writing endpoints on 127.0.0.1.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(configs.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(preview.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(compare.router, prefix="/api")
app.include_router(campaigns.router, prefix="/api")
app.include_router(calc.router, prefix="/api")
app.include_router(workspace_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__, "project_root": str(REPO_ROOT)}


# ── user interfaces ──────────────────────────────────────────────────────────
# Studio 2 (web/, built to web/dist) at "/", the classic UI at "/classic".
if FRONTEND_DIR.is_dir():
    app.mount("/classic/assets", StaticFiles(directory=FRONTEND_DIR), name="classic-assets")

    @app.get("/classic", include_in_schema=False)
    @app.get("/classic/", include_in_schema=False)
    def classic_index() -> HTMLResponse:
        html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace('"/assets/', '"/classic/assets/'))


if (WEB_DIST / "index.html").is_file():
    if (WEB_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="web-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str) -> FileResponse:
        """Static files from web/dist, everything else is the single-page app."""
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        f = (WEB_DIST / path).resolve()
        if path and f.is_file() and f.is_relative_to(WEB_DIST):
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
elif FRONTEND_DIR.is_dir():
    # web/ not built: the classic UI stays the default
    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/classic/")
