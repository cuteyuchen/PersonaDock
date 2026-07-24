"""Local PersonaDock Web control plane."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Header, HTTPException

from persona_dock.registry import RegistryService

from .app import create_app as _create_base_app
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

    register_v3_routes(app, require_token, RegistryService)
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
    if token:
        print("API bearer-token authentication is enabled.")
    uvicorn.run(create_app(token=token), host=host, port=port, log_level="info")


__all__ = ["create_app", "run_server"]
