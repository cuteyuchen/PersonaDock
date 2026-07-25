from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from persona_dock.application import PersonaApplicationService, RevisionStore, canonical_hash
from persona_dock.core.models import load_canonical_persona
from persona_dock.registry import RegistryService
from persona_dock.registry.database import RegistryDatabase
from persona_dock.web import create_app


def _persona(tmp_path: Path) -> tuple[Path, dict, RegistryService]:
    registry = RegistryService(RegistryDatabase(tmp_path / "registry.db"))
    result = PersonaApplicationService(registry).create(
        tmp_path / "personas" / "xiaoyou",
        persona_id="xiaoyou",
        name="小柚",
        locale="zh-CN",
    )
    root = Path(result["project"])
    return root, load_canonical_persona(root), registry


def test_revision_store_deduplicates_objects_and_keeps_manifests(tmp_path: Path) -> None:
    _, model, _ = _persona(tmp_path)
    store = RevisionStore(tmp_path / "revisions")

    first = store.capture("xiaoyou", model, source="baseline", summary="initial")
    second = store.capture("xiaoyou", model, source="manual", summary="same content")

    assert first.content_hash == second.content_hash
    assert first.revision_id != second.revision_id
    assert second.parent_revision_id == first.revision_id
    assert len(list((tmp_path / "revisions" / "xiaoyou" / "objects").glob("*.json"))) == 1
    assert len(store.list("xiaoyou")) == 2
    assert store.model("xiaoyou", first.revision_id) == model


def test_revision_diff_reports_high_risk_boundaries(tmp_path: Path) -> None:
    _, model, _ = _persona(tmp_path)
    store = RevisionStore(tmp_path / "revisions")
    changed = dict(model)
    changed["boundaries"] = [dict(item) for item in model["boundaries"]]
    changed["boundaries"][0]["rule"] = "不得在用户未授权时传播私人资料"

    diff = store.diff(model, changed)
    assert diff["changed"] is True
    assert diff["changed_boundaries"]
    assert diff["risk"]["level"] == "high"
    assert diff["before_hash"] == canonical_hash(model)
    assert diff["after_hash"] == canonical_hash(changed)


def test_restore_plan_is_bound_to_current_content(tmp_path: Path) -> None:
    _, model, _ = _persona(tmp_path)
    changed = dict(model)
    changed["summary"] = "changed"
    target = dict(model)
    target["summary"] = "target"

    first = RevisionStore.restore_plan("xiaoyou", model, "revision-1", target)
    stale = RevisionStore.restore_plan("xiaoyou", changed, "revision-1", target)

    assert first["requires_confirmation"] is True
    assert first["target_hash"] == stale["target_hash"]
    assert first["current_hash"] != stale["current_hash"]
    assert first["plan_hash"] != stale["plan_hash"]


def test_phase_three_editor_routes_are_registered() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    for path in (
        "/api/v1/personas/{persona_id}/canonical",
        "/api/v1/personas/{persona_id}/revisions",
        "/api/v1/personas/{persona_id}/revisions/{revision_id}",
        "/api/v1/personas/{persona_id}/diff",
        "/api/v1/personas/{persona_id}/revisions/{revision_id}/restore/preview",
        "/api/v1/personas/{persona_id}/revisions/{revision_id}/restore",
        "/api/v1/personas/{persona_id}/validation",
        "/api/v1/personas/{persona_id}/tests",
        "/api/v1/personas/{persona_id}/compile-preview",
        "/api/v1/personas/{persona_id}/migrate-v3",
        "/assets/{asset_name}",
    ):
        assert path in paths


def test_phase_three_shell_loads_editor_without_ai_dashboard_styling() -> None:
    root = files("persona_dock.web.static")
    html = root.joinpath("index.html").read_text(encoding="utf-8")
    css = root.joinpath("editor.css").read_text(encoding="utf-8")
    javascript = root.joinpath("editor.js").read_text(encoding="utf-8")

    assert 'href="/assets/editor.css"' in html
    assert 'src="/assets/editor.js"' in html
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert ".source-editor" in css
    assert ".diff-row" in css
    assert "/compile-preview" in javascript
    assert "/restore/preview" in javascript
    assert "Revision" in javascript
    assert "chat" not in javascript.lower()
