from __future__ import annotations

from importlib.resources import files
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from persona_dock.session_engine import SessionSummaryEngine, SessionSummaryError


class SessionPreviewRequest(BaseModel):
    path: str = Field(min_length=1)
    session_id: str | None = None
    max_turns: int = Field(default=20, ge=2, le=200)
    include_emotional_context: bool = False


class SessionImportRequest(BaseModel):
    path: str = Field(min_length=1)
    source_adapter: str = Field(default="file", pattern="^(file|hermes|openclaw)$")
    runtime_instance_id: str | None = None
    session_id: str | None = None


class NativeSessionCollectRequest(BaseModel):
    runtime_instance_id: str = Field(min_length=1)
    session_identifier: str = Field(min_length=1)


class SessionReviewRequest(BaseModel):
    reviewer: str = Field(default="web", min_length=1)
    scope: str = Field(default="shared", pattern="^(local-only|shared)$")
    reason: str | None = None


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
    def sessions_page() -> str:
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

    @app.post("/api/sessions/preview")
    def preview_session(
        request: SessionPreviewRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().preview_file(
                request.path,
                session_id=request.session_id,
                max_turns=request.max_turns,
                include_emotional_context=request.include_emotional_context,
            )
        except (SessionSummaryError, ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sessions/{persona_id}/import")
    def import_session(
        persona_id: str,
        request: SessionImportRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().import_file(
                persona_id,
                request.path,
                source_adapter=request.source_adapter,
                runtime_instance_id=request.runtime_instance_id,
                session_id=request.session_id,
            )
        except (SessionSummaryError, ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sessions/{persona_id}/collect")
    def collect_native_session(
        persona_id: str,
        request: NativeSessionCollectRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return engine().collect_native(
                persona_id,
                request.runtime_instance_id,
                request.session_identifier,
            )
        except (SessionSummaryError, ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sessions/{persona_id}/summaries")
    def list_session_summaries(
        persona_id: str,
        status: str | None = Query(default=None, pattern="^(pending|approved|rejected|superseded)$"),
        source_adapter: str | None = Query(default=None, pattern="^(file|hermes|openclaw)$"),
        _: None = Depends(require_token),
    ) -> list[dict[str, Any]]:
        try:
            return [
                value.to_dict()
                for value in engine().sessions.list(
                    persona_id,
                    status=status,
                    source_adapter=source_adapter,
                )
            ]
        except (SessionSummaryError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sessions/summaries/{summary_id}/approve")
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

    @app.post("/api/sessions/summaries/{summary_id}/reject")
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
