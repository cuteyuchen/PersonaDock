from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from persona_dock.web import create_app


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("PERSONADOCK_PERSONA_ROOTS", str(tmp_path / "personas"))
    return TestClient(create_app())


def test_vue_phase_two_routes_are_registered() -> None:
    paths = {route.path for route in create_app().routes}
    assert "/api/v1/personas/{persona_id}/canonical/commit" in paths
    assert "/api/v1/personas/{persona_id}/revisions" in paths
    assert "/api/v1/personas/{persona_id}/diff" in paths
    assert "/api/v1/personas/{persona_id}/tests" in paths


def test_guarded_canonical_commit_rejects_stale_editor(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/api/v1/personas",
        json={"id": "vue-editor", "name": "Vue Editor", "locale": "zh-CN", "folder": "vue-editor"},
    )
    assert created.status_code == 201, created.text

    loaded = client.get("/api/v1/personas/vue-editor/canonical")
    assert loaded.status_code == 200, loaded.text
    payload = loaded.json()
    original_hash = payload["content_hash"]
    model = payload["model"]
    model["summary"] = "first guarded save"

    saved = client.put(
        "/api/v1/personas/vue-editor/canonical/commit",
        json={
            "model": model,
            "expected_content_hash": original_hash,
            "summary": "Vue guarded save",
            "source": "manual",
        },
    )
    assert saved.status_code == 200, saved.text
    saved_value = saved.json()
    assert saved_value["revision"]["content_hash"] != original_hash
    assert saved_value["diff"]["changed"] is True
    assert saved_value["validation"]["ok"] is True

    stale_model = dict(model)
    stale_model["summary"] = "stale overwrite"
    stale = client.put(
        "/api/v1/personas/vue-editor/canonical/commit",
        json={
            "model": stale_model,
            "expected_content_hash": original_hash,
            "summary": "stale save",
            "source": "manual",
        },
    )
    assert stale.status_code == 409, stale.text
    detail = stale.json()["detail"]
    assert detail["expected_content_hash"] == original_hash
    assert detail["current_content_hash"] == saved_value["revision"]["content_hash"]


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
