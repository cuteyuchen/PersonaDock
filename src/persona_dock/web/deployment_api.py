from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from persona_dock.adapters.hermes import HermesAdapterError
from persona_dock.adapters.openclaw import OpenClawAdapterError
from persona_dock.application import (
    ArtifactApplicationService,
    ArtifactStore,
    DeploymentApplicationService,
    DeploymentPlanChangedError,
)
from persona_dock.registry import RegistryService

from .jobs import JobStore


class DeploymentPlanRequest(BaseModel):
    target: Literal["hermes", "openclaw"]
    persona_id: str | None = Field(default=None, max_length=120)
    package_path: str | None = Field(default=None, max_length=2048)
    profile: str | None = Field(default=None, max_length=120)
    activate: bool = False
    alias: bool = False
    agent: str | None = Field(default=None, max_length=120)
    workspace: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, max_length=240)
    bindings: list[str] = Field(default_factory=list, max_length=40)
    take_ownership: bool = False
    container: str | None = Field(default=None, max_length=240)
    ssh_host: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_source_and_target_options(self) -> "DeploymentPlanRequest":
        if bool(self.persona_id) == bool(self.package_path):
            raise ValueError("provide exactly one of persona_id or package_path")
        if self.target == "hermes" and any(
            (self.agent, self.workspace, self.model, self.bindings, self.take_ownership, self.ssh_host)
        ):
            raise ValueError("OpenClaw options are not valid for Hermes deployment")
        if self.target == "openclaw" and any((self.profile, self.activate, self.alias)):
            raise ValueError("Hermes options are not valid for OpenClaw deployment")
        if self.container and self.ssh_host:
            raise ValueError("container and ssh_host are mutually exclusive")
        return self


class DeploymentApplyRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=120)
    confirmation_token: str = Field(min_length=16, max_length=512)


class DeploymentRollbackRequest(BaseModel):
    confirmation: Literal["ROLLBACK"]


def _jobs() -> JobStore:
    return JobStore()


def _service(registry_factory: Callable[[], RegistryService]) -> DeploymentApplicationService:
    registry = registry_factory()
    return DeploymentApplicationService(
        registry,
        ArtifactApplicationService(registry, ArtifactStore()),
    )


def _raise_http(error: Exception) -> None:
    if isinstance(error, KeyError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, PermissionError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, DeploymentPlanChangedError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, (HermesAdapterError, OpenClawAdapterError, ValueError, OSError)):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


def _job(
    store: JobStore,
    *,
    kind: str,
    label: str,
    input: dict[str, Any],
    operation: Callable[[], dict[str, Any]],
    persona_id: str | None = None,
) -> dict[str, Any]:
    record = store.create(kind=kind, label=label, input=input, persona_id=persona_id)
    store.update(record.id, status="running", progress=10)
    try:
        result = operation()
    except Exception as error:
        store.update(record.id, status="failed", error=str(error))
        raise
    completed = store.update(record.id, status="success", output=result)
    return {"job": completed.to_dict(), "result": result}


def register_deployment_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], RegistryService],
    service_factory: Callable[[], DeploymentApplicationService] | None = None,
    job_store_factory: Callable[[], JobStore] = _jobs,
) -> None:
    resolve_service = service_factory or (lambda: _service(registry_factory))

    @app.get("/api/v1/deployments")
    def deployments(
        limit: int = Query(default=100, ge=1, le=200),
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        values = resolve_service().list(limit=limit)
        return {"items": values, "count": len(values)}

    @app.get("/api/v1/deployments/{deployment_id}")
    def deployment(
        deployment_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        value = resolve_service().get(deployment_id)
        if value is None:
            raise HTTPException(status_code=404, detail="deployment not found")
        return value

    @app.post("/api/v1/deployment-plans", status_code=201)
    def create_deployment_plan(
        request: DeploymentPlanRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return resolve_service().create_plan(request.model_dump())
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/deployments")
    def apply_deployment(
        request: DeploymentApplyRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = resolve_service()
            planned = service.get(request.plan_id)
            persona_id = None
            if planned:
                persona_id = planned.get("request", {}).get("persona_id")
            # The confirmation token is intentionally excluded from Job state.
            return _job(
                job_store_factory(),
                kind="deployment.apply",
                label="应用原生部署计划",
                input={"plan_id": request.plan_id},
                persona_id=persona_id,
                operation=lambda: service.apply(
                    request.plan_id,
                    confirmation_token=request.confirmation_token,
                ),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/deployments/{deployment_id}/rollback")
    def rollback_deployment(
        deployment_id: str,
        request: DeploymentRollbackRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = resolve_service()
            current = service.get(deployment_id)
            persona_id = None
            if current:
                persona_id = current.get("request", {}).get("persona_id")
            return _job(
                job_store_factory(),
                kind="deployment.rollback",
                label="回滚原生部署",
                input={"deployment_id": deployment_id},
                persona_id=persona_id,
                operation=lambda: service.rollback(deployment_id),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")


__all__ = [
    "DeploymentApplyRequest",
    "DeploymentPlanRequest",
    "DeploymentRollbackRequest",
    "register_deployment_routes",
]
