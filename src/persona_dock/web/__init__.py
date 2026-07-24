"""Local PersonaDock Web control plane."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException

from persona_dock import __version__
from persona_dock.registry import RegistryService

from .app import create_app as _create_base_app
from .hermes_api import register_hermes_routes
from .openclaw_api import register_openclaw_routes
from .sync_api import register_sync_routes
from .v3_api import register_v3_routes


def create_app(token: str | None = None):
    app = _create_base_app(token=token)

    def require_token(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        if token is None:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/api/health"
            and "GET" in getattr(route, "methods", set())
        )
    ]

    @app.get("/api/health")
    def health(_: None = Depends(require_token)) -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "phase": 6,
            "control_plane": "local",
            "registry": RegistryService().summary(),
            "canonical_schema": 3,
            "persona_pack_format": 2,
            "hermes_native_adapter": True,
            "openclaw_native_adapter": True,
            "workspace_state_separation": True,
            "governed_memory_sync": True,
            "raw_session_sync": False,
        }

    register_v3_routes(app, require_token, RegistryService)
    register_hermes_routes(app, require_token, RegistryService)
    register_openclaw_routes(app, require_token, RegistryService)
    register_sync_routes(app, require_token, RegistryService)
    return app


def run_server(
    host: str = "127.0.0.1",
    port: int = 8732,
    token: str | None = None,
    open_browser: bool = True,
) -> None:
    import ipaddress
    import threading
    import webbrowser

    import uvicorn

    token = token or os.environ.get("PERSONADOCK_WEB_TOKEN")
    try:
        address = ipaddress.ip_address(host)
        is_loopback = address.is_loopback
    except ValueError:
        is_loopback = host.lower() == "localhost"

    if not is_loopback and not token:
        raise ValueError(
            "non-loopback Web binding requires --token or PERSONADOCK_WEB_TOKEN"
        )

    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{url_host}:{port}"
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    print(f"PersonaDock Web control plane: {url}")
    print(f"Canonical Persona editor: {url}/canonical")
    print(f"Hermes native Profile manager: {url}/hermes")
    print(f"OpenClaw native Agent manager: {url}/openclaw")
    print(f"Sync policy and review center: {url}/sync")
    if token:
        print("API bearer-token authentication is enabled.")
    uvicorn.run(create_app(token=token), host=host, port=port, log_level="info")


__all__ = ["create_app", "run_server"]
