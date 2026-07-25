from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from persona_dock.adoption import AdoptionError, adopt_runtime_instance, adoption_preview
from persona_dock.application import PersonaApplicationService
from persona_dock.discovery import discover_runtime_instances
from persona_dock.exports import EXPORT_FORMATS, export_registered_persona
from persona_dock.registry import RegistryService

from .jobs import JobStore
from .paths import PersonaPathPolicy, WebPathError


class PersonaCreateRequest(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    locale: str = Field(default="zh-CN", min_length=2, max_length=32)
    folder: str | None = Field(default=None, max_length=240)


class PersonaRegisterRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class RuntimeDiscoveryRequest(BaseModel):
    target: Literal["hermes", "openclaw"] | None = None


class AdoptionRequest(BaseModel):
    instance_id: str = Field(min_length=1)
    persona_id: str | None = None
    name: str | None = None
    destination: str | None = None
    link_existing: bool = False


class PersonaExportRequest(BaseModel):
    format: Literal["personapack", "hermes-profile", "openclaw-workspace"]
    include_memory: bool = False


def _job_store() -> JobStore:
    return JobStore()


def _paths() -> PersonaPathPolicy:
    return PersonaPathPolicy()


def register_lifecycle_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], RegistryService],
    job_store_factory: Callable[[], JobStore] = _job_store,
    path_policy_factory: Callable[[], PersonaPathPolicy] = _paths,
) -> None:
    def personas() -> PersonaApplicationService:
        return PersonaApplicationService(registry_factory())

    @app.get("/api/v1/persona-roots")
    def persona_roots(_: None = Depends(require_token)) -> dict[str, object]:
        return path_policy_factory().to_dict()

    @app.get("/api/v1/personas")
    def list_personas(_: None = Depends(require_token)) -> dict[str, Any]:
        values = personas().list()
        return {"items": values, "count": len(values)}

    @app.get("/api/v1/personas/{persona_id}")
    def get_persona(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        value = personas().get(persona_id)
        if value is None:
            raise HTTPException(status_code=404, detail="persona not found")
        return value

    @app.post("/api/v1/personas", status_code=201)
    def create_persona(
        request: PersonaCreateRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = personas()
        if service.get(request.id) is not None:
            raise HTTPException(status_code=409, detail="persona id is already registered")
        try:
            policy = path_policy_factory()
            destination = policy.resolve_new(request.folder or request.id)
            value = service.create(
                destination,
                persona_id=request.id,
                name=request.name,
                locale=request.locale,
            )
        except WebPathError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except (ValueError, FileExistsError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return value

    @app.post("/api/v1/personas/register")
    def register_persona(
        request: PersonaRegisterRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            path = path_policy_factory().resolve_existing(request.path)
            return personas().register(path)
        except WebPathError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/v1/runtimes/discover")
    def discover_runtimes(
        request: RuntimeDiscoveryRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = job_store_factory()
        job = store.create(
            kind="runtime.discover",
            label="扫描运行实例",
            input=request.model_dump(),
        )
        store.update(job.id, status="running", progress=10)
        try:
            result = discover_runtime_instances(
                request.target,
                registry=registry_factory(),
            ).to_dict()
        except Exception as error:
            store.update(job.id, status="failed", error=str(error))
            raise HTTPException(status_code=500, detail=str(error)) from error
        completed = store.update(job.id, status="success", output=result)
        return {"job": completed.to_dict(), "result": result}

    @app.post("/api/v1/adoptions/preview")
    def preview_runtime_adoption(
        request: AdoptionRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return adoption_preview(
                request.instance_id,
                persona_id=request.persona_id,
                name=request.name,
                destination=request.destination,
                registry=registry_factory(),
            )
        except AdoptionError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/adoptions")
    def adopt_runtime(
        request: AdoptionRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = job_store_factory()
        job = store.create(
            kind="runtime.adopt",
            label="接管运行实例",
            input=request.model_dump(),
            runtime_instance_id=request.instance_id,
        )
        store.update(job.id, status="running", progress=10)
        try:
            result = adopt_runtime_instance(
                request.instance_id,
                persona_id=request.persona_id,
                name=request.name,
                destination=request.destination,
                link_existing=request.link_existing,
                registry=registry_factory(),
            ).to_dict()
        except (AdoptionError, FileExistsError, FileNotFoundError, ValueError) as error:
            store.update(job.id, status="failed", error=str(error))
            raise HTTPException(status_code=400, detail=str(error)) from error
        completed = store.update(job.id, status="success", output=result)
        return {"job": completed.to_dict(), "result": result}

    @app.post("/api/v1/personas/{persona_id}/exports")
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
                registry=registry_factory(),
            )
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        value = result.to_dict()
        value["download_url"] = f"/api/exports/download?path={result.path}"
        return value


__all__ = ["register_lifecycle_routes"]
