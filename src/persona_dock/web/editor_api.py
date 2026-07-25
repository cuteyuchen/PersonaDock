from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from persona_dock.application import RevisionStore, canonical_hash
from persona_dock.compiler import compile_soul
from persona_dock.core.migration import migrate_project_to_v3
from persona_dock.core.models import load_canonical_persona, normalize_canonical_persona
from persona_dock.core.testing import run_persona_tests
from persona_dock.io import dump_yaml, load_yaml
from persona_dock.project import PROJECT_FILE, validate_project
from persona_dock.registry import RegistryService

from .jobs import JobStore


class CanonicalSaveRequest(BaseModel):
    model: dict[str, Any]
    summary: str = Field(default="", max_length=500)
    source: Literal["manual", "ai", "import", "migration"] = "manual"


class RevisionDiffRequest(BaseModel):
    before_revision_id: str | None = None
    after_revision_id: str | None = None


class RevisionRestoreRequest(BaseModel):
    plan_hash: str = Field(min_length=64, max_length=64)
    summary: str = Field(default="恢复历史 Revision", max_length=500)


class MigrationRequest(BaseModel):
    dry_run: bool = True
    backup: bool = True


def _revision_store() -> RevisionStore:
    return RevisionStore()


def _job_store() -> JobStore:
    return JobStore()


def _source(service: RegistryService, persona_id: str) -> Path:
    persona = service.get_persona(persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="persona not found")
    if not persona.source_path:
        raise HTTPException(status_code=409, detail="persona has no source project")
    root = Path(persona.source_path).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=409, detail="persona source project is unavailable")
    return root


def _register(service: RegistryService, root: Path, model: dict[str, Any]) -> None:
    service.register_persona(
        persona_id=str(model["id"]),
        name=str(model["name"]),
        version=str(model["version"]),
        source_path=root,
        schema_version=int(model["schema_version"]),
        summary=str(model.get("summary", "")),
    )


def _capture_baseline(
    store: RevisionStore,
    persona_id: str,
    current: dict[str, Any],
) -> None:
    latest = store.latest(persona_id)
    if latest is None or latest.content_hash != canonical_hash(current):
        errors: list[str] = []
        store.capture(
            persona_id,
            current,
            source="baseline",
            summary="编辑前自动快照",
            validation_result={"ok": not errors, "errors": errors},
        )


def _resolve_model(
    store: RevisionStore,
    persona_id: str,
    current: dict[str, Any],
    revision_id: str | None,
) -> dict[str, Any]:
    if revision_id is None or revision_id == "current":
        return current
    try:
        return store.model(persona_id, revision_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="revision not found") from error


def register_editor_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], RegistryService],
    revision_store_factory: Callable[[], RevisionStore] = _revision_store,
    job_store_factory: Callable[[], JobStore] = _job_store,
) -> None:
    @app.get("/api/v1/personas/{persona_id}/canonical")
    def canonical_model(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        root = _source(service, persona_id)
        try:
            model = load_canonical_persona(root)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"model": model, "content_hash": canonical_hash(model)}

    @app.put("/api/v1/personas/{persona_id}/canonical")
    def save_canonical_model(
        persona_id: str,
        request: CanonicalSaveRequest,
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
        if after["id"] != persona_id:
            raise HTTPException(status_code=400, detail="Persona ID cannot be changed")

        _capture_baseline(store, persona_id, before)
        project_file = root / PROJECT_FILE
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
            },
        )
        return {
            "model": after,
            "revision": revision.to_dict(),
            "diff": diff,
            "validation": {"ok": True, "errors": []},
            "tests": tests,
        }

    @app.get("/api/v1/personas/{persona_id}/revisions")
    def list_revisions(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        root = _source(service, persona_id)
        current = load_canonical_persona(root)
        store = revision_store_factory()
        _capture_baseline(store, persona_id, current)
        values = store.list(persona_id)
        return {
            "current_hash": canonical_hash(current),
            "items": [item.to_dict() for item in values],
            "count": len(values),
        }

    @app.get("/api/v1/personas/{persona_id}/revisions/{revision_id}")
    def get_revision(
        persona_id: str,
        revision_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = revision_store_factory()
        record = store.get(persona_id, revision_id)
        if record is None:
            raise HTTPException(status_code=404, detail="revision not found")
        return {"revision": record.to_dict(), "model": store.model(persona_id, revision_id)}

    @app.post("/api/v1/personas/{persona_id}/diff")
    def revision_diff(
        persona_id: str,
        request: RevisionDiffRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        current = load_canonical_persona(_source(service, persona_id))
        store = revision_store_factory()
        before = _resolve_model(store, persona_id, current, request.before_revision_id)
        after = _resolve_model(store, persona_id, current, request.after_revision_id)
        return store.diff(before, after)

    @app.post("/api/v1/personas/{persona_id}/revisions/{revision_id}/restore/preview")
    def preview_restore(
        persona_id: str,
        revision_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        current = load_canonical_persona(_source(service, persona_id))
        store = revision_store_factory()
        try:
            target = store.model(persona_id, revision_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="revision not found") from error
        return {
            "plan": store.restore_plan(persona_id, current, revision_id, target),
            "diff": store.diff(current, target),
        }

    @app.post("/api/v1/personas/{persona_id}/revisions/{revision_id}/restore")
    def restore_revision(
        persona_id: str,
        revision_id: str,
        request: RevisionRestoreRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        root = _source(service, persona_id)
        current = load_canonical_persona(root)
        store = revision_store_factory()
        try:
            target = store.model(persona_id, revision_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="revision not found") from error
        plan = store.restore_plan(persona_id, current, revision_id, target)
        if request.plan_hash != plan["plan_hash"]:
            raise HTTPException(
                status_code=409,
                detail="restore plan is stale; preview the restore again",
            )
        _capture_baseline(store, persona_id, current)
        project_file = root / PROJECT_FILE
        original = project_file.read_bytes()
        project_file.write_text(dump_yaml(target), encoding="utf-8")
        errors = validate_project(root)
        if errors:
            project_file.write_bytes(original)
            raise HTTPException(status_code=422, detail={"message": "restore validation failed", "errors": errors})
        tests = run_persona_tests(root).to_dict()
        restored = store.capture(
            persona_id,
            target,
            source="restore",
            summary=request.summary,
            validation_result={"ok": True, "errors": []},
            test_result=tests,
        )
        _register(service, root, target)
        service.journal(
            "canonical-persona-revision-restored",
            persona_id=persona_id,
            payload={
                "target_revision_id": revision_id,
                "created_revision_id": restored.revision_id,
                "plan_hash": plan["plan_hash"],
            },
        )
        return {"model": target, "revision": restored.to_dict(), "tests": tests}

    @app.get("/api/v1/personas/{persona_id}/validation")
    def validate_persona(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        root = _source(registry_factory(), persona_id)
        errors = validate_project(root)
        return {"ok": not errors, "errors": errors}

    @app.post("/api/v1/personas/{persona_id}/tests")
    def test_persona(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        root = _source(registry_factory(), persona_id)
        store = job_store_factory()
        job = store.create(kind="persona.test", label="运行人格场景测试", persona_id=persona_id)
        store.update(job.id, status="running", progress=10)
        try:
            result = run_persona_tests(root).to_dict()
        except ValueError as error:
            store.update(job.id, status="failed", error=str(error))
            raise HTTPException(status_code=409, detail=str(error)) from error
        status = "success" if result.get("ok") else "failed"
        completed = store.update(
            job.id,
            status=status,
            output=result,
            error=None if status == "success" else "one or more persona tests failed",
        )
        return {"job": completed.to_dict(), "result": result}

    @app.get("/api/v1/personas/{persona_id}/compile-preview")
    def compile_preview(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        root = _source(registry_factory(), persona_id)
        model = load_canonical_persona(root)
        soul = compile_soul(model)
        skill_path = root / "skills" / "persona" / "SKILL.md"
        skill = skill_path.read_text(encoding="utf-8") if skill_path.is_file() else ""
        budgets = model.get("budgets", {})
        return {
            "soul": soul,
            "skill": skill,
            "soul_chars": len(soul),
            "target_chars": budgets.get("target_chars"),
            "hard_limit_chars": budgets.get("hard_limit_chars"),
            "targets": model.get("targets", []),
        }

    @app.post("/api/v1/personas/{persona_id}/migrate-v3")
    def migrate_persona(
        persona_id: str,
        request: MigrationRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        root = _source(service, persona_id)
        value = load_yaml(root / PROJECT_FILE)
        from_schema = int(value.get("schema_version", 0))
        if request.dry_run:
            return {
                "persona_id": persona_id,
                "from_schema": from_schema,
                "to_schema": 3,
                "changed": from_schema != 3,
                "requires_confirmation": from_schema != 3,
                "backup": request.backup,
            }
        try:
            result = migrate_project_to_v3(root, in_place=True, backup=request.backup)
        except (ValueError, FileExistsError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        model = load_canonical_persona(Path(result.project))
        revision = revision_store_factory().capture(
            persona_id,
            model,
            source="migration",
            summary=f"Schema {result.from_schema} → {result.to_schema}",
            validation_result={"ok": True, "errors": []},
        )
        _register(service, Path(result.project), model)
        return {**result.to_dict(), "revision": revision.to_dict()}


__all__ = ["register_editor_routes"]
