from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import auth, camera, config, files, frames, logs, overlay, plugins, status, stream, system, terminal
from .security import require_admin, require_preview


def create_app(static_dir: Path | None = None, cors_origins: tuple[str, ...] = ()) -> FastAPI:
    app = FastAPI(title="caelum", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        # The browser only sends the session cookie to the origin that set
        # it, so a wildcard here would be both useless and rejected by every
        # browser for credentialed requests. Vite's dev server proxies /api
        # to the backend, making even development same-origin; this list is
        # only for pointing a dev frontend at a camera on the LAN, plus any
        # `cors_origins` (the static caelum-viewer reads /api/files cookie-
        # less, so it only works with `auth.preview_access: public`).
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", *cors_origins],
        allow_origin_regex=r"http://localhost:\d+|http://127\.0\.0\.1:\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth routes handle their own access levels (login must stay reachable
    # to anonymous callers); everything else is blanket-guarded per router,
    # so adding a route can never accidentally ship it unauthenticated.
    app.include_router(auth.router, prefix="/api")

    preview_only = [Depends(require_preview)]
    admin_only = [Depends(require_admin)]

    app.include_router(status.router, prefix="/api", dependencies=preview_only)
    app.include_router(config.router, prefix="/api", dependencies=admin_only)
    app.include_router(camera.router, prefix="/api", dependencies=admin_only)
    app.include_router(plugins.router, prefix="/api", dependencies=admin_only)
    app.include_router(system.router, prefix="/api", dependencies=admin_only)
    # files/frames/overlay declare per-route levels: reads are preview, writes admin.
    app.include_router(files.router, prefix="/api")
    app.include_router(frames.router, prefix="/api")
    app.include_router(overlay.router, prefix="/api")
    # Websocket routers authorize inside the handler — a dependency raising
    # HTTPException after the handshake has no way to reach the client.
    app.include_router(stream.router)  # paths are already fully qualified (/api/frame/*, /ws/*)
    app.include_router(terminal.router)
    app.include_router(logs.router)  # paths are already fully qualified (/api/logs, /ws/logs)

    if static_dir is not None and static_dir.exists():
        # local-web's built assets — the Pi runs a single service, no nginx.
        # Unauthenticated on purpose: it is the login page, and the bundle
        # contains no data of its own.
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="local-web")

    return app
