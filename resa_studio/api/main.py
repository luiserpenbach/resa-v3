"""RESA Studio FastAPI application."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from resa_studio import __version__
from resa_studio.api.routes import artifacts, campaigns, compare, configs, preview, projects, runs
from resa_studio.settings import FRONTEND_DIR, REPO_ROOT

app = FastAPI(
    title="RESA Studio",
    description="UI API for Rocket Engine Sizing & Analysis",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__, "project_root": str(REPO_ROOT)}


if FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
