from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from persona_dock.adapters.openclaw import OpenClawAdapter, OpenClawAdapterError
from persona_dock.openclaw_deployment import (
    apply_openclaw_deployment,
    plan_openclaw_deployment,
    rollback_openclaw_deployment,
)
from persona_dock.openclaw_memory import (
    pull_openclaw_memory_candidates,
    push_openclaw_shared_memory,
)


class OpenClawPlanRequest(BaseModel):
    package: str = Field(min_length=1)
    agent: str | None = None
    workspace: str | None = None
    model: str | None = None
    bindings: list[str] = Field(default_factory=list)
    take_ownership: bool = False
    container: str | None = None
    ssh_host: str | None = None


class OpenClawRollbackRequest(BaseModel):
    agent: str = Field(min_length=1)
    snapshot: str | None = None
    workspace: str | None = None
    delete_agent: bool = False
    container: str | None = None
    ssh_host: str | None = None


class OpenClawMemoryRequest(BaseModel):
    persona_id: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    container: str | None = None
    ssh_host: str | None = None


def _html() -> str:
    return files("persona_dock.web.static").joinpath("openclaw.html").read_text(encoding="utf-8")


def register_openclaw_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], Any],
) -> None:
    @app.get("/openclaw", response_class=HTMLResponse, include_in_schema=False)
    def openclaw_page() -> str:
        return _html()

    @app.get("/api/openclaw/doctor")
    def openclaw_doctor(
        container: str | None = None,
        ssh_host: str | None = None,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        return OpenClawAdapter(container=container, ssh_host=ssh_host).doctor().to_dict()

    @app.get("/api/openclaw/agents")
    def openclaw_agents(
        container: str | None = Query(default=None),
        ssh_host: str | None = Query(default=None),
        _: None = Depends(require_token),
    ) -> list[dict[str, Any]]:
        try:
            return [
                agent.to_dict()
                for agent in OpenClawAdapter(
                    container=container,
                    ssh_host=ssh_host,
                ).list_agents()
            ]
        except OpenClawAdapterError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/openclaw/plans")
    def openclaw_plan(
        request: OpenClawPlanRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        adapter = OpenClawAdapter(
            container=request.container,
            ssh_host=request.ssh_host,
        )
        try:
            return plan_openclaw_deployment(
                Path(request.package),
                agent=request.agent,
                agent_explicit=request.agent is not None,
                workspace=request.workspace,
                model=request.model,
                bindings=request.bindings,
                take_ownership=request.take_ownership,
                container=request.container,
                ssh_host=request.ssh_host,
                adapter=adapter,
            ).to_dict()
        except (OpenClawAdapterError, FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/openclaw/deployments")
    def openclaw_deploy(
        request: OpenClawPlanRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        adapter = OpenClawAdapter(
            container=request.container,
            ssh_host=request.ssh_host,
        )
        try:
            plan = plan_openclaw_deployment(
                Path(request.package),
                agent=request.agent,
                agent_explicit=request.agent is not None,
                workspace=request.workspace,
                model=request.model,
                bindings=request.bindings,
                take_ownership=request.take_ownership,
                container=request.container,
                ssh_host=request.ssh_host,
                adapter=adapter,
            )
            return apply_openclaw_deployment(
                plan,
                adapter=adapter,
                registry=registry_factory(),
            ).to_dict()
        except (OpenClawAdapterError, FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/openclaw/rollback")
    def openclaw_rollback(
        request: OpenClawRollbackRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return rollback_openclaw_deployment(
                agent=request.agent,
                snapshot=request.snapshot,
                workspace=request.workspace,
                delete_agent=request.delete_agent,
                container=request.container,
                ssh_host=request.ssh_host,
                adapter=OpenClawAdapter(
                    container=request.container,
                    ssh_host=request.ssh_host,
                ),
                registry=registry_factory(),
            )
        except (OpenClawAdapterError, FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/openclaw/memory/pull")
    def openclaw_memory_pull(
        request: OpenClawMemoryRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return pull_openclaw_memory_candidates(
                request.persona_id,
                agent_id=request.agent,
                container=request.container,
                ssh_host=request.ssh_host,
                adapter=OpenClawAdapter(
                    container=request.container,
                    ssh_host=request.ssh_host,
                ),
                registry=registry_factory(),
            )
        except (OpenClawAdapterError, FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/openclaw/memory/push")
    def openclaw_memory_push(
        request: OpenClawMemoryRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return push_openclaw_shared_memory(
                request.persona_id,
                agent_id=request.agent,
                container=request.container,
                ssh_host=request.ssh_host,
                adapter=OpenClawAdapter(
                    container=request.container,
                    ssh_host=request.ssh_host,
                ),
                registry=registry_factory(),
            )
        except (OpenClawAdapterError, FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
