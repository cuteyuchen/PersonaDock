from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from persona_dock.session_engine import SessionSummaryError
from persona_dock.session_runtime import SessionSummaryEngine
from persona_dock.sync_engine import SyncEngine, SyncError

from .jobs import JobStore


class MemoryApplyRequest(BaseModel):
    include_definitions: bool = False
    confirmed: bool = False


class SessionApplyRequest(BaseModel):
    confirmed: bool = False


def _jobs() -> JobStore:
    return JobStore()


def _run_job(
    store: JobStore,
    *,
    kind: str,
    label: str,
    persona_id: str,
    input: dict[str, Any],
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    job = store.create(
        kind=kind,
        label=label,
        input=input,
        persona_id=persona_id,
    )
    store.update(job.id, status="running", progress=10)
    try:
        result = operation()
    except Exception as error:
        store.update(job.id, status="failed", error=str(error))
        raise
    completed = store.update(job.id, status="success", output=result)
    return {"job": completed.to_dict(), "result": result}


def register_governance_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], Any],
    job_store_factory: Callable[[], JobStore] = _jobs,
    sync_engine_factory: Callable[[], Any] | None = None,
    session_engine_factory: Callable[[], Any] | None = None,
) -> None:
    resolve_sync = sync_engine_factory or (lambda: SyncEngine(registry_factory()))
    resolve_sessions = session_engine_factory or (
        lambda: SessionSummaryEngine(registry_factory())
    )

    @app.post("/api/v1/governance/memory/{persona_id}/collect")
    def collect_memory(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        engine = resolve_sync()
        try:
            return _run_job(
                job_store_factory(),
                kind="memory.collect",
                label="收集 Memory 候选",
                persona_id=persona_id,
                input={"persona_id": persona_id},
                operation=lambda: engine.collect(persona_id),
            )
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/v1/governance/memory/{persona_id}/apply")
    def apply_memory(
        persona_id: str,
        request: MemoryApplyRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        if not request.confirmed:
            raise HTTPException(
                status_code=400,
                detail="Memory apply requires explicit confirmation",
            )
        engine = resolve_sync()
        try:
            return _run_job(
                job_store_factory(),
                kind="memory.apply",
                label="应用 Memory 同步计划",
                persona_id=persona_id,
                input={
                    "persona_id": persona_id,
                    "include_definitions": request.include_definitions,
                },
                operation=lambda: engine.apply(
                    engine.plan(persona_id),
                    include_definitions=request.include_definitions,
                ),
            )
        except (SyncError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/v1/governance/sessions/{persona_id}/collect")
    def collect_sessions(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        engine = resolve_sessions()
        try:
            return _run_job(
                job_store_factory(),
                kind="session.collect",
                label="收集 Session Summary",
                persona_id=persona_id,
                input={"persona_id": persona_id},
                operation=lambda: engine.collect(persona_id),
            )
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/v1/governance/sessions/{persona_id}/apply")
    def apply_sessions(
        persona_id: str,
        request: SessionApplyRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        if not request.confirmed:
            raise HTTPException(
                status_code=400,
                detail="Session Summary apply requires explicit confirmation",
            )
        engine = resolve_sessions()
        try:
            return _run_job(
                job_store_factory(),
                kind="session.apply",
                label="应用 Session Summary 传播计划",
                persona_id=persona_id,
                input={"persona_id": persona_id},
                operation=lambda: engine.apply(engine.plan(persona_id)),
            )
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error


__all__ = [
    "MemoryApplyRequest",
    "SessionApplyRequest",
    "register_governance_routes",
]
