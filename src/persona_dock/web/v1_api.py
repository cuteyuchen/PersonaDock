from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from persona_dock import __version__
from persona_dock.adapters.base import ADAPTER_API_VERSION
from persona_dock.registry import RegistryService

from .capabilities import capability_summary, list_capabilities
from .jobs import JOB_STATUSES, TERMINAL_JOB_STATUSES, JobStore
from .version import WEB_CONTROL_PLANE_VERSION, WEB_REFACTOR_PHASE

_NAVIGATION = (
    {"id": "overview", "label": "概览", "route": "#/overview", "phase": 1},
    {"id": "personas", "label": "人格", "route": "#/personas", "phase": 2},
    {"id": "ai-studio", "label": "AI 人格工作室", "route": "#/ai-studio", "phase": 7},
    {"id": "diff", "label": "差异中心", "route": "#/diff", "phase": 3},
    {"id": "runtimes", "label": "运行实例", "route": "#/runtimes", "phase": 2},
    {"id": "deployments", "label": "部署", "route": "#/deployments", "phase": 5},
    {"id": "memory", "label": "Memory 同步", "route": "#/memory", "phase": 6},
    {"id": "sessions", "label": "Session Summary", "route": "#/sessions", "phase": 6},
    {"id": "packages", "label": "PersonaPack 与信任", "route": "#/packages", "phase": 4},
    {"id": "backups", "label": "备份", "route": "#/backups", "phase": 4},
    {"id": "character-cards", "label": "Character Card", "route": "#/character-cards", "phase": 4},
    {"id": "adapters", "label": "Adapter 与 Skill", "route": "#/adapters", "phase": 4},
    {"id": "jobs", "label": "任务中心", "route": "#/jobs", "phase": 1},
    {"id": "settings", "label": "系统设置", "route": "#/settings", "phase": 7},
)


def _job_store() -> JobStore:
    return JobStore()


def _job_or_404(store: JobStore, job_id: str):
    value = store.get(job_id)
    if value is None:
        raise HTTPException(status_code=404, detail="job not found")
    return value


def _sse(value: dict[str, Any], *, event: str = "message", event_id: int | None = None) -> str:
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n\n"


def _event_stream(store: JobStore, job_id: str, after_id: int) -> Iterator[str]:
    cursor = max(0, after_id)
    idle_rounds = 0
    while idle_rounds < 30:
        events = store.events(job_id, after_id=cursor)
        if events:
            idle_rounds = 0
            for item in events:
                cursor = item.id
                yield _sse(item.to_dict(), event="job-event", event_id=item.id)
        else:
            idle_rounds += 1
            yield ": keep-alive\n\n"

        job = store.get(job_id)
        if job is None:
            yield _sse({"id": job_id, "status": "missing"}, event="job-close")
            return
        if job.status in TERMINAL_JOB_STATUSES and not events:
            yield _sse(job.to_dict(), event="job-close")
            return
        time.sleep(1)


def register_v1_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], RegistryService],
    job_store_factory: Callable[[], JobStore] = _job_store,
) -> None:
    @app.get("/api/v1/meta")
    def meta(_: None = Depends(require_token)) -> dict[str, Any]:
        return {
            "product": "PersonaDock",
            "version": __version__,
            "api_version": 1,
            "web_control_plane": WEB_CONTROL_PLANE_VERSION,
            "web_refactor_phase": WEB_REFACTOR_PHASE,
            "control_plane": "local-first",
            "canonical_schema": 3,
            "persona_pack_format": 2,
            "adapter_api_version": ADAPTER_API_VERSION,
            "capabilities": capability_summary(),
            "navigation": list(_NAVIGATION),
        }

    @app.get("/api/v1/capabilities")
    def capabilities(
        status: Literal["ready", "legacy", "planned"] | None = None,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        return {
            "summary": capability_summary(),
            "items": list_capabilities(status=status),
        }

    @app.get("/api/v1/dashboard")
    def dashboard(_: None = Depends(require_token)) -> dict[str, Any]:
        service = registry_factory()
        personas = service.list_personas()
        instances = service.list_runtime_instances()
        jobs = job_store_factory().list(limit=8)
        managed = sum(1 for item in instances if item.managed)
        return {
            "registry": service.summary(),
            "metrics": {
                "personas": len(personas),
                "runtime_instances": len(instances),
                "managed_instances": managed,
                "unmanaged_instances": len(instances) - managed,
                "active_jobs": sum(
                    1
                    for item in jobs
                    if item.status in {"queued", "running", "waiting-review"}
                ),
                "failed_jobs": sum(1 for item in jobs if item.status == "failed"),
            },
            "personas": [item.to_dict() for item in personas[:8]],
            "instances": [item.to_dict() for item in instances[:8]],
            "jobs": [item.to_dict() for item in jobs],
        }

    @app.get("/api/v1/jobs")
    def jobs(
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = None,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        if status is not None and status not in JOB_STATUSES:
            raise HTTPException(status_code=400, detail="unsupported job status")
        values = job_store_factory().list(limit=limit, status=status)  # type: ignore[arg-type]
        return {"items": [item.to_dict() for item in values], "count": len(values)}

    @app.get("/api/v1/jobs/{job_id}")
    def job(job_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
        store = job_store_factory()
        value = _job_or_404(store, job_id)
        return {
            **value.to_dict(),
            "events": [item.to_dict() for item in store.events(job_id)],
        }

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
        store = job_store_factory()
        _job_or_404(store, job_id)
        return store.cancel(job_id).to_dict()

    @app.get("/api/v1/jobs/{job_id}/events")
    def job_events(
        job_id: str,
        after_id: int = Query(default=0, ge=0),
        _: None = Depends(require_token),
    ) -> StreamingResponse:
        store = job_store_factory()
        _job_or_404(store, job_id)
        return StreamingResponse(
            _event_stream(store, job_id, after_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )


__all__ = ["register_v1_routes"]
