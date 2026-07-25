from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from persona_dock import __version__
from persona_dock.adoption import AdoptionError, adopt_runtime_instance, adoption_preview
from persona_dock.deployment.plans import build_deployment_plan
from persona_dock.discovery import discover_runtime_instances
from persona_dock.doctor import doctor_report
from persona_dock.exports import EXPORT_FORMATS, export_registered_persona
from persona_dock.registry import RegistryService
from persona_dock.registry.database import registry_root


class DeploymentPlanRequest(BaseModel):
    package: str = Field(min_length=1)
    target: str = Field(pattern="^(hermes|openclaw|generic)$")
    path: str | None = None
    container: str | None = None


class DiscoveryRequest(BaseModel):
    target: str | None = Field(default=None, pattern="^(hermes|openclaw)$")


class AdoptionRequest(BaseModel):
    instance_id: str = Field(min_length=1)
    persona_id: str | None = None
    name: str | None = None
    destination: str | None = None
    link_existing: bool = False


class PersonaExportRequest(BaseModel):
    format: str = Field(pattern="^(personapack|hermes-profile|openclaw-workspace)$")
    include_memory: bool = False


def _static_text(name: str) -> str:
    return files("persona_dock.web.static").joinpath(name).read_text(encoding="utf-8")


def _index_html() -> str:
    return _static_text("index.html")


def _safe_export_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    root = (registry_root() / "exports").resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=403, detail="export path is outside PersonaDock exports") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="export file not found")
    return path


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

    @app.get("/assets/app.css", include_in_schema=False)
    def web_styles() -> Response:
        return Response(
            _static_text("app.css"),
            media_type="text/css; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/assets/app.js", include_in_schema=False)
    def web_application() -> Response:
        return Response(
            _static_text("app.js"),
            media_type="text/javascript; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/health")
    def health(_: None = Depends(require_token)) -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "phase": 2,
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

    @app.post("/api/adoptions/preview")
    def preview_adoption(
        request: AdoptionRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return adoption_preview(
                request.instance_id,
                persona_id=request.persona_id,
                name=request.name,
                destination=request.destination,
                registry=registry(),
            )
        except AdoptionError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/adoptions")
    def adopt(
        request: AdoptionRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return adopt_runtime_instance(
                request.instance_id,
                persona_id=request.persona_id,
                name=request.name,
                destination=request.destination,
                link_existing=request.link_existing,
                registry=registry(),
            ).to_dict()
        except (AdoptionError, FileExistsError, FileNotFoundError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/personas/{persona_id}/exports")
    def export_persona(
        persona_id: str,
        request: PersonaExportRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        if request.format not in EXPORT_FORMATS:
            raise HTTPException(status_code=400, detail="unsupported export format")
        try:
            result = export_registered_persona(
                persona_id,
                request.format,
                include_memory=request.include_memory,
                registry=registry(),
            )
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        value = result.to_dict()
        value["download_url"] = f"/api/exports/download?path={result.path}"
        return value

    @app.get("/api/exports/download")
    def download_export(
        path: str,
        _: None = Depends(require_token),
    ) -> FileResponse:
        resolved = _safe_export_path(path)
        return FileResponse(resolved, filename=resolved.name)

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
