from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from persona_dock.adapters.hermes import HermesAdapter, HermesAdapterError
from persona_dock.hermes_deployment import (
    apply_hermes_deployment,
    plan_hermes_deployment,
    rollback_hermes_deployment,
)
from persona_dock.hermes_memory import (
    pull_hermes_memory_candidates,
    push_hermes_shared_memory,
)


class HermesPlanRequest(BaseModel):
    package: str = Field(min_length=1)
    profile: str | None = None
    activate: bool = False
    alias: bool = False
    container: str | None = None


class HermesRollbackRequest(BaseModel):
    profile: str = Field(min_length=1)
    snapshot: str | None = None
    container: str | None = None
    activate: bool = False


class HermesMemoryRequest(BaseModel):
    persona_id: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    container: str | None = None


def _html() -> str:
    return files("persona_dock.web.static").joinpath("hermes.html").read_text(encoding="utf-8")


def register_hermes_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], Any],
) -> None:
    @app.get("/hermes", response_class=HTMLResponse, include_in_schema=False)
    def hermes_page() -> str:
        return _html()

    @app.get("/api/hermes/doctor")
    def hermes_doctor(
        container: str | None = None,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        return HermesAdapter(container=container).doctor().to_dict()

    @app.get("/api/hermes/profiles")
    def hermes_profiles(
        container: str | None = Query(default=None),
        _: None = Depends(require_token),
    ) -> list[dict[str, Any]]:
        try:
            return [
                profile.to_dict()
                for profile in HermesAdapter(container=container).list_profiles()
            ]
        except HermesAdapterError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/hermes/plans")
    def hermes_plan(
        request: HermesPlanRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        adapter = HermesAdapter(container=request.container)
        try:
            return plan_hermes_deployment(
                Path(request.package),
                profile=request.profile,
                profile_explicit=request.profile is not None,
                activate=request.activate,
                alias=request.alias,
                container=request.container,
                adapter=adapter,
            ).to_dict()
        except (HermesAdapterError, FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/hermes/deployments")
    def hermes_deploy(
        request: HermesPlanRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        adapter = HermesAdapter(container=request.container)
        try:
            plan = plan_hermes_deployment(
                Path(request.package),
                profile=request.profile,
                profile_explicit=request.profile is not None,
                activate=request.activate,
                alias=request.alias,
                container=request.container,
                adapter=adapter,
            )
            return apply_hermes_deployment(
                plan,
                adapter=adapter,
                registry=registry_factory(),
            ).to_dict()
        except (HermesAdapterError, FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/hermes/rollback")
    def hermes_rollback(
        request: HermesRollbackRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return rollback_hermes_deployment(
                profile=request.profile,
                snapshot=request.snapshot,
                container=request.container,
                activate=request.activate,
                adapter=HermesAdapter(container=request.container),
                registry=registry_factory(),
            )
        except (HermesAdapterError, FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/hermes/memory/pull")
    def hermes_memory_pull(
        request: HermesMemoryRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return pull_hermes_memory_candidates(
                request.persona_id,
                profile=request.profile,
                container=request.container,
                adapter=HermesAdapter(container=request.container),
                registry=registry_factory(),
            )
        except (HermesAdapterError, FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/hermes/memory/push")
    def hermes_memory_push(
        request: HermesMemoryRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return push_hermes_shared_memory(
                request.persona_id,
                profile=request.profile,
                container=request.container,
                adapter=HermesAdapter(container=request.container),
                registry=registry_factory(),
            )
        except (HermesAdapterError, FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
