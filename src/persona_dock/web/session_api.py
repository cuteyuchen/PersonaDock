from __future__ import annotations

from importlib.resources import files
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from persona_dock.session_engine import SessionSummaryError
from persona_dock.session_runtime import SessionSummaryEngine


class SessionPolicyUpdateRequest(BaseModel):
    config: dict[str, Any]
    replace: bool = False


class SessionReviewRequest(BaseModel):
    reviewer: str = Field(default="web", min_length=1)
    scope: str = Field(default="shared", pattern="^(local-only|shared)$")
    reason: str | None = None


class ManualSessionSummaryRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    title: str = Field(default="Manual summary", max_length=200)
    pending_tasks: list[str] = Field(default_factory=list, max_length=20)
    emotional_context: dict[str, Any] = Field(default_factory=dict)
    sensitivity: str = Field(default="internal", pattern="^(public|internal|private|restricted)$")


class SessionApplyRequest(BaseModel):
    confirmed: bool = False


class RawSessionPreviewRequest(BaseModel):
    runtime_instance_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    experimental: bool = False


def _html() -> str:
    return files("persona_dock.web.static").joinpath("sessions.html").read_text(encoding="utf-8")


def register_session_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], Any],
) -> None:
    def engine() -> SessionSummaryEngine:
        return SessionSummaryEngine(registry_factory())

    @app.get("/sessions", response_class=HTMLResponse, include_in_schema=False)
    def session_page() -> str:
        return _html()

    @app.get("/api/sessions/{persona_id}")
    def session_dashboard(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().dashboard(persona_id)
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sessions/{persona_id}/policy")
    def session_policy(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().session.get_policy(persona_id).to_dict()
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.put("/api/sessions/{persona_id}/policy")
    def update_session_policy(
        persona_id: str,
        request: SessionPolicyUpdateRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().session.set_policy(
                persona_id,
                request.config,
                replace=request.replace,
            ).to_dict()
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sessions/{persona_id}/collect")
    def collect_session_summaries(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().collect(persona_id)
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sessions/{persona_id}/items")
    def session_summary_items(
        persona_id: str,
        status: str | None = Query(default=None, pattern="^(pending|approved|rejected|superseded)$"),
        source_adapter: str | None = Query(default=None, pattern="^(hermes|openclaw|manual)$"),
        sensitivity: str | None = Query(default=None, pattern="^(public|internal|private|restricted)$"),
        _: None = Depends(require_token),
    ) -> list[dict[str, Any]]:
        try:
            return [
                item.to_dict()
                for item in engine().session.list_summaries(
                    persona_id,
                    status=status,
                    source_adapter=source_adapter,
                    sensitivity=sensitivity,
                )
            ]
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sessions/{persona_id}/manual")
    def add_manual_session_summary(
        persona_id: str,
        request: ManualSessionSummaryRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().add_manual(
                persona_id,
                summary=request.summary,
                title=request.title,
                pending_tasks=request.pending_tasks,
                emotional_context=request.emotional_context,
                sensitivity=request.sensitivity,
            ).to_dict()
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/session-summaries/{summary_id}/approve")
    def approve_session_summary(
        summary_id: str,
        request: SessionReviewRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().approve(
                summary_id,
                reviewer=request.reviewer,
                sync_scope=request.scope,
            ).to_dict()
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/session-summaries/{summary_id}/reject")
    def reject_session_summary(
        summary_id: str,
        request: SessionReviewRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().reject(
                summary_id,
                reviewer=request.reviewer,
                reason=request.reason,
            ).to_dict()
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sessions/{persona_id}/plan")
    def session_summary_plan(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().plan(persona_id).to_dict()
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sessions/{persona_id}/apply")
    def apply_session_summary_plan(
        persona_id: str,
        request: SessionApplyRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        if not request.confirmed:
            raise HTTPException(status_code=400, detail="Session Summary apply requires explicit confirmation")
        service = engine()
        try:
            return service.apply(service.plan(persona_id))
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sessions/{persona_id}/preview")
    def preview_raw_session(
        persona_id: str,
        request: RawSessionPreviewRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().raw_preview(
                persona_id,
                request.runtime_instance_id,
                request.session_id,
                confirmed_experimental=request.experimental,
            )
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
