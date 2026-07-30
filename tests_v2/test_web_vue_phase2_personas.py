from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException

from persona_dock.application import PersonaApplicationService, RevisionStore, canonical_hash
from persona_dock.core.models import load_canonical_persona
from persona_dock.registry import RegistryService
from persona_dock.registry.database import RegistryDatabase
from persona_dock.web import create_app
from persona_dock.web.vue_editor_api import (
    GuardedCanonicalSaveRequest,
    register_vue_editor_routes,
)


def test_vue_phase_two_routes_are_registered() -> None:
    paths = {route.path for route in create_app().routes}
    assert "/api/v1/personas/{persona_id}/canonical/commit" in paths
    assert "/api/v1/personas/{persona_id}/revisions" in paths
    assert "/api/v1/personas/{persona_id}/diff" in paths
    assert "/api/v1/personas/{persona_id}/tests" in paths


def test_guarded_canonical_commit_rejects_stale_editor(tmp_path: Path) -> None:
    registry = RegistryService(RegistryDatabase(tmp_path / "registry.db"))
    project = tmp_path / "personas" / "vue-editor"
    PersonaApplicationService(registry).create(
        project,
        persona_id="vue-editor",
        name="Vue Editor",
        locale="zh-CN",
    )
    revisions = RevisionStore(tmp_path / "revisions")
    app = FastAPI()
    register_vue_editor_routes(
        app,
        lambda: None,
        lambda: registry,
        lambda: revisions,
    )
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/personas/{persona_id}/canonical/commit"
    )

    model = load_canonical_persona(project)
    original_hash = canonical_hash(model)
    model["summary"] = "first guarded save"
    saved = endpoint(
        "vue-editor",
        GuardedCanonicalSaveRequest(
            model=model,
            expected_content_hash=original_hash,
            summary="Vue guarded save",
            source="manual",
        ),
        None,
    )
    assert saved["revision"]["content_hash"] != original_hash
    assert saved["diff"]["changed"] is True
    assert saved["validation"]["ok"] is True

    stale_model = dict(model)
    stale_model["summary"] = "stale overwrite"
    with pytest.raises(HTTPException) as captured:
        endpoint(
            "vue-editor",
            GuardedCanonicalSaveRequest(
                model=stale_model,
                expected_content_hash=original_hash,
                summary="stale save",
                source="manual",
            ),
            None,
        )
    assert captured.value.status_code == 409
    detail = captured.value.detail
    assert isinstance(detail, dict)
    assert detail["expected_content_hash"] == original_hash
    assert detail["current_content_hash"] == saved["revision"]["content_hash"]


def test_vue_phase_two_source_contracts() -> None:
    root = Path(__file__).resolve().parents[1] / "frontend"
    router = (root / "src/router/index.ts").read_text(encoding="utf-8")
    editor = (root / "src/views/PersonaEditorView.vue").read_text(encoding="utf-8")
    package = (root / "package.json").read_text(encoding="utf-8")

    for route in (
        "/personas/new",
        "/personas/register",
        "/personas/:personaId/editor",
        "/personas/:personaId/revisions",
        "/personas/:personaId/tests",
    ):
        assert route in router
    assert "MonacoJsonEditor" in editor
    assert "expected_content_hash" in (root / "src/api/personas.ts").read_text(encoding="utf-8")
    assert '"monaco-editor"' in package
    assert '"vee-validate"' in package
    assert '"zod"' in package
