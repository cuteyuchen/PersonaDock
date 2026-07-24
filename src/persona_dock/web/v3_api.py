from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from persona_dock.core.diff import diff_personas
from persona_dock.core.migration import migrate_project_to_v3
from persona_dock.core.models import load_canonical_persona, normalize_canonical_persona
from persona_dock.core.testing import run_persona_tests
from persona_dock.io import dump_yaml
from persona_dock.project import PROJECT_FILE, validate_project
from persona_dock.registry import RegistryService


class CanonicalUpdateRequest(BaseModel):
    model: dict[str, Any]


class MigrationRequest(BaseModel):
    in_place: bool = True
    output: str | None = None
    backup: bool = True


class DiffRequest(BaseModel):
    before_persona_id: str
    after_persona_id: str


def _source(service: RegistryService, persona_id: str) -> Path:
    persona = service.get_persona(persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="persona not found")
    if not persona.source_path:
        raise HTTPException(status_code=400, detail="persona has no source project")
    path = Path(persona.source_path).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="persona source project is unavailable")
    return path


def _register(service: RegistryService, root: Path, value: dict[str, Any]) -> None:
    service.register_persona(
        persona_id=str(value["id"]),
        name=str(value["name"]),
        version=str(value["version"]),
        source_path=root,
        schema_version=int(value["schema_version"]),
        summary=str(value["summary"]),
    )


def register_v3_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], RegistryService],
) -> None:
    @app.get("/canonical", response_class=HTMLResponse, include_in_schema=False)
    def canonical_editor() -> str:
        return files("persona_dock.web.static").joinpath("canonical.html").read_text(encoding="utf-8")

    @app.get("/api/personas/{persona_id}/canonical")
    def canonical_model(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        root = _source(service, persona_id)
        try:
            return load_canonical_persona(root)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.put("/api/personas/{persona_id}/canonical")
    def update_canonical_model(
        persona_id: str,
        request: CanonicalUpdateRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        root = _source(service, persona_id)
        try:
            value = normalize_canonical_persona(request.model)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if value.get("id") != persona_id:
            raise HTTPException(status_code=400, detail="Persona ID cannot be changed in this editor")

        project_file = root / PROJECT_FILE
        original = project_file.read_bytes()
        backup = root / ".personadock" / "editor-backups" / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-companion.yaml"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(original)
        project_file.write_text(dump_yaml(value), encoding="utf-8")
        errors = validate_project(root)
        if errors:
            project_file.write_bytes(original)
            raise HTTPException(
                status_code=422,
                detail={"message": "Canonical Persona validation failed", "errors": errors},
            )
        _register(service, root, value)
        service.journal(
            "canonical-persona-updated",
            persona_id=persona_id,
            payload={"backup": str(backup), "version": value["version"]},
        )
        return {"model": value, "backup": str(backup), "valid": True}

    @app.post("/api/personas/{persona_id}/migrate-v3")
    def migrate_persona(
        persona_id: str,
        request: MigrationRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        root = _source(service, persona_id)
        try:
            result = migrate_project_to_v3(
                root,
                output=Path(request.output) if request.output else None,
                in_place=request.in_place,
                backup=request.backup,
            )
        except (ValueError, FileExistsError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        migrated_root = Path(result.project)
        value = load_canonical_persona(migrated_root)
        _register(service, migrated_root, value)
        service.journal(
            "canonical-persona-migrated",
            persona_id=persona_id,
            payload=result.to_dict(),
        )
        return result.to_dict()

    @app.get("/api/personas/{persona_id}/tests")
    def persona_tests(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        root = _source(service, persona_id)
        try:
            return run_persona_tests(root).to_dict()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/personas/diff")
    def persona_diff(
        request: DiffRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        service = registry_factory()
        before = _source(service, request.before_persona_id)
        after = _source(service, request.after_persona_id)
        try:
            return diff_personas(before, after).to_dict()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
