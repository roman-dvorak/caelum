from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import camera, config, plugins, status, stream


def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="caelum", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(status.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.include_router(camera.router, prefix="/api")
    app.include_router(plugins.router, prefix="/api")
    app.include_router(stream.router)  # paths are already fully qualified (/api/frame/*, /ws/*)

    if static_dir is not None and static_dir.exists():
        # local-web's built assets — the Pi runs a single service, no nginx.
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="local-web")

    return app
