from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from persona_dock.application import RevisionStore, canonical_hash
from persona_dock.core.models import load_canonical_persona, normalize_canonical_persona
from persona_dock.core.testing import run_persona_tests
from persona_dock.io import dump_yaml
from persona_dock.project import PROJECT_FILE, validate_project
from persona_dock.registry import RegistryService

from .editor_api import _capture_baseline, _register, _source


class GuardedCanonicalSaveRequest(BaseModel):
    model: dict[str, Any]
    expected_content_hash: str = Field(min_length=64, max_length=64)
    summary: str = Field(default="", max_length=500)
    source: Literal["manual", "ai", "import", "migration"] = "manual"


def _revision_store() -> RevisionStore:
    return RevisionStore()


def register_vue_editor_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], RegistryService],
    revision_store_factory: Callable[[], RevisionStore] = _revision_store,
) -> None:
    @app.put("/api/v1/personas/{persona_id}/canonical/commit")
    def commit_canonical_model(
        persona_id: str,
        request: GuardedCanonicalSaveRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        store = revision_store_factory()
        root = _source(service, persona_id)
        try:
            before = load_canonical_persona(root)
            after = normalize_canonical_persona(request.model)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        current_hash = canonical_hash(before)
        if current_hash != request.expected_content_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Canonical Persona changed after this editor loaded",
                    "expected_content_hash": request.expected_content_hash,
                    "current_content_hash": current_hash,
                },
            )
        if after["id"] != persona_id:
            raise HTTPException(status_code=400, detail="Persona ID cannot be changed")

        _capture_baseline(store, persona_id, before)
        project_file = Path(root) / PROJECT_FILE
        original = project_file.read_bytes()
        project_file.write_text(dump_yaml(after), encoding="utf-8")
        errors = validate_project(root)
        if errors:
            project_file.write_bytes(original)
            raise HTTPException(
                status_code=422,
                detail={"message": "Canonical Persona validation failed", "errors": errors},
            )

        tests = run_persona_tests(root).to_dict()
        revision = store.capture(
            persona_id,
            after,
            source=request.source,
            summary=request.summary or "保存 Canonical Persona",
            validation_result={"ok": True, "errors": []},
            test_result=tests,
        )
        _register(service, root, after)
        diff = store.diff(before, after)
        service.journal(
            "canonical-persona-revision-created",
            persona_id=persona_id,
            payload={
                "revision_id": revision.revision_id,
                "content_hash": revision.content_hash,
                "source": request.source,
                "risk": diff["risk"],
                "expected_content_hash": request.expected_content_hash,
            },
        )
        return {
            "model": after,
            "revision": revision.to_dict(),
            "diff": diff,
            "validation": {"ok": True, "errors": []},
            "tests": tests,
        }


__all__ = ["register_vue_editor_routes"]
