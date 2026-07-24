from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from persona_dock import __version__
from persona_dock.deployment.plans import build_deployment_plan
from persona_dock.discovery import discover_runtime_instances
from persona_dock.doctor import doctor_report
from persona_dock.registry import RegistryService


class DeploymentPlanRequest(BaseModel):
    package: str = Field(min_length=1)
    target: str = Field(pattern="^(hermes|openclaw|generic)$")
    path: str | None = None
    container: str | None = None


class DiscoveryRequest(BaseModel):
    target: str | None = Field(default=None, pattern="^(hermes|openclaw)$")


def _index_html() -> str:
    return files("persona_dock.web.static").joinpath("index.html").read_text(encoding="utf-8")


def create_app(token: str | None = None) -> FastAPI:
    app = FastAPI(
        title="PersonaDock Control Plane",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
    )

    def require_token(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        if token is None:
            return
        expected = f"Bearer {token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    def registry() -> RegistryService:
        return RegistryService()

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return _index_html()

    @app.get("/api/health")
    def health(_: None = Depends(require_token)) -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "phase": 1,
            "control_plane": "local",
            "registry": registry().summary(),
        }

    @app.get("/api/doctor")
    def doctor(_: None = Depends(require_token)) -> dict[str, Any]:
        return doctor_report()

    @app.get("/api/registry")
    def registry_summary(_: None = Depends(require_token)) -> dict[str, Any]:
        return registry().summary()

    @app.get("/api/personas")
    def personas(_: None = Depends(require_token)) -> list[dict[str, Any]]:
        return [record.to_dict() for record in registry().list_personas()]

    @app.get("/api/personas/{persona_id}")
    def persona(persona_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
        service = registry()
        record = service.get_persona(persona_id)
        if record is None:
            raise HTTPException(status_code=404, detail="persona not found")
        return {
            **record.to_dict(),
            "bindings": [binding.to_dict() for binding in service.list_bindings(persona_id)],
        }

    @app.get("/api/instances")
    def instances(
        adapter: str | None = Query(default=None, pattern="^(hermes|openclaw)$"),
        managed: bool | None = None,
        _: None = Depends(require_token),
    ) -> list[dict[str, Any]]:
        return [
            record.to_dict()
            for record in registry().list_runtime_instances(adapter=adapter, managed=managed)
        ]

    @app.get("/api/instances/{instance_id}")
    def instance(instance_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
        record = registry().get_runtime_instance(instance_id)
        if record is None:
            raise HTTPException(status_code=404, detail="runtime instance not found")
        return record.to_dict()

    @app.post("/api/discover")
    def discover(
        request: DiscoveryRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        return discover_runtime_instances(request.target, registry=registry()).to_dict()

    @app.post("/api/plans/deploy")
    def deployment_plan(
        request: DeploymentPlanRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        plan = build_deployment_plan(
            Path(request.package),
            request.target,
            request.path,
            request.container,
        )
        return plan.to_dict()

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
    if token:
        print("API bearer-token authentication is enabled.")
    uvicorn.run(create_app(token=token), host=host, port=port, log_level="info")
