"""Local PersonaDock Web control plane."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException

from persona_dock import __version__
from persona_dock.adapters.base import ADAPTER_API_VERSION
from persona_dock.registry import RegistryService

from .app import create_app as _create_base_app
from .artifact_api import register_artifact_routes
from .deployment_api import register_deployment_routes
from .editor_api import register_editor_routes
from .governance_api import register_governance_routes
from .hermes_api import register_hermes_routes
from .lifecycle_api import register_lifecycle_routes
from .openclaw_api import register_openclaw_routes
from .phase_assets import register_phase_asset_routes
from .session_api import register_session_routes
from .sync_api import register_sync_routes
from .v1_api import register_v1_routes
from .v3_api import register_v3_routes
from .version import WEB_CONTROL_PLANE_VERSION, WEB_REFACTOR_PHASE


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
            "phase": 8,
            "web_control_plane": WEB_CONTROL_PLANE_VERSION,
            "web_refactor_phase": WEB_REFACTOR_PHASE,
            "control_plane": "local",
            "registry": RegistryService().summary(),
            "canonical_schema": 3,
            "persona_pack_format": 2,
            "adapter_api_version": ADAPTER_API_VERSION,
            "hermes_native_adapter": True,
            "openclaw_native_adapter": True,
            "workspace_state_separation": True,
            "governed_memory_sync": True,
            "reviewed_session_summaries": True,
            "raw_session_sync": False,
            "raw_session_preview": "experimental-disabled-by-default",
            "persona_pack_signatures": "detached-ed25519-v1",
            "encrypted_private_backup": "aes-256-gcm-scrypt-v1",
            "character_card_compatibility": ["v2-json", "v3-json", "png-import", "charx"],
            "stable_1_0_contract": True,
        }

    register_phase_asset_routes(app)
    register_v1_routes(app, require_token, RegistryService)
    register_lifecycle_routes(app, require_token, RegistryService)
    register_editor_routes(app, require_token, RegistryService)
    register_artifact_routes(app, require_token, RegistryService)
    register_deployment_routes(app, require_token, RegistryService)
    register_governance_routes(app, require_token, RegistryService)
    register_v3_routes(app, require_token, RegistryService)
    register_hermes_routes(app, require_token, RegistryService)
    register_openclaw_routes(app, require_token, RegistryService)
    register_sync_routes(app, require_token, RegistryService)
    register_session_routes(app, require_token, RegistryService)
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

    print(f"PersonaDock Web {WEB_CONTROL_PLANE_VERSION}.0 control plane: {url}")
    print(f"Canonical Persona editor: {url}/canonical")
    print(f"Hermes native Profile manager: {url}/hermes")
    print(f"OpenClaw native Agent manager: {url}/openclaw")
    print(f"Sync policy and review center: {url}/sync")
    print(f"Session Summary review center: {url}/sessions")
    if token:
        print("API bearer-token authentication is enabled.")
    uvicorn.run(create_app(token=token), host=host, port=port, log_level="info")


__all__ = ["create_app", "run_server"]
