from __future__ import annotations

from importlib.resources import files
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from persona_dock.sync_engine import SyncEngine, SyncError
from persona_dock.sync_registry import SyncRegistry


class PolicyUpdateRequest(BaseModel):
    config: dict[str, Any]
    replace: bool = False


class ReviewRequest(BaseModel):
    reviewer: str = Field(default="web", min_length=1)
    scope: str | None = Field(default=None, pattern="^(local-only|shared)$")
    reason: str | None = None


class ConflictResolutionRequest(BaseModel):
    resolution: str = Field(pattern="^(keep-existing|replace|keep-both)$")
    reviewer: str = Field(default="web", min_length=1)


class ApplySyncRequest(BaseModel):
    include_definitions: bool = False


def _html() -> str:
    return files("persona_dock.web.static").joinpath("sync.html").read_text(encoding="utf-8")


def register_sync_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], Any],
) -> None:
    def engine() -> SyncEngine:
        return SyncEngine(registry_factory())

    @app.get("/sync", response_class=HTMLResponse, include_in_schema=False)
    def sync_page() -> str:
        return _html()

    @app.get("/api/sync/{persona_id}")
    def sync_dashboard(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().dashboard(persona_id)
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sync/{persona_id}/policy")
    def sync_policy(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().sync.get_policy(persona_id).to_dict()
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.put("/api/sync/{persona_id}/policy")
    def update_sync_policy(
        persona_id: str,
        request: PolicyUpdateRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().sync.set_policy(
                persona_id,
                request.config,
                replace=request.replace,
            ).to_dict()
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sync/{persona_id}/collect")
    def collect_sync_candidates(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().collect(persona_id)
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sync/{persona_id}/memory")
    def memory_items(
        persona_id: str,
        status: str | None = Query(default=None, pattern="^(pending|approved|rejected|superseded)$"),
        sensitivity: str | None = Query(default=None, pattern="^(public|internal|private|restricted)$"),
        source_adapter: str | None = Query(default=None, pattern="^(hermes|openclaw)$"),
        _: None = Depends(require_token),
    ) -> list[dict[str, Any]]:
        try:
            return [
                item.to_dict()
                for item in engine().sync.list_memory_items(
                    persona_id,
                    status=status,
                    sensitivity=sensitivity,
                    source_adapter=source_adapter,
                )
            ]
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sync/memory/{item_id}/approve")
    def approve_memory(
        item_id: str,
        request: ReviewRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().approve(
                item_id,
                reviewer=request.reviewer,
                sync_scope=request.scope,
            ).to_dict()
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sync/memory/{item_id}/reject")
    def reject_memory(
        item_id: str,
        request: ReviewRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().reject(
                item_id,
                reviewer=request.reviewer,
                reason=request.reason,
            ).to_dict()
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sync/{persona_id}/conflicts")
    def sync_conflicts(
        persona_id: str,
        status: str | None = Query(default=None, pattern="^(pending|resolved)$"),
        _: None = Depends(require_token),
    ) -> list[dict[str, Any]]:
        try:
            return [
                conflict.to_dict()
                for conflict in engine().sync.list_conflicts(persona_id, status=status)
            ]
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sync/conflicts/{conflict_id}/resolve")
    def resolve_sync_conflict(
        conflict_id: str,
        request: ConflictResolutionRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().resolve_conflict(
                conflict_id,
                request.resolution,
                reviewer=request.reviewer,
            )
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sync/{persona_id}/plan")
    def sync_plan(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().plan(persona_id).to_dict()
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sync/{persona_id}/apply")
    def apply_sync_plan(
        persona_id: str,
        request: ApplySyncRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = engine()
        try:
            plan = service.plan(persona_id)
            return service.apply(
                plan,
                include_definitions=request.include_definitions,
            )
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sync/{persona_id}/runs")
    def sync_runs(
        persona_id: str,
        limit: int = Query(default=50, ge=1, le=200),
        _: None = Depends(require_token),
    ) -> list[dict[str, Any]]:
        try:
            return engine().sync.list_runs(persona_id, limit=limit)
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sync/{persona_id}/propagation")
    def propagation_log(
        persona_id: str,
        limit: int = Query(default=100, ge=1, le=500),
        _: None = Depends(require_token),
    ) -> list[dict[str, Any]]:
        try:
            return engine().sync.propagation_log(persona_id, limit=limit)
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
