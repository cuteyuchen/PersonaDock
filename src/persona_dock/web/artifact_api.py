from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from persona_dock.application import (
    ArtifactApplicationService,
    ArtifactPathError,
    ArtifactStore,
)
from persona_dock.character_card import CharacterCardError
from persona_dock.package_trust import PackageTrustError
from persona_dock.private_backup import PrivateBackupError
from persona_dock.registry import RegistryService
from persona_dock.skill_install import TARGETS as SKILL_TARGETS

from .jobs import JobStore
from .paths import PersonaPathPolicy, WebPathError


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content_base64: str = Field(min_length=1)


class BuildRequest(BaseModel):
    targets: list[Literal["hermes", "openclaw", "generic"]] | None = None


class ArtifactPathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)


class KeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SignRequest(BaseModel):
    package_path: str = Field(min_length=1, max_length=2048)
    key_id: str = Field(min_length=1, max_length=160)


class VerifyRequest(BaseModel):
    package_path: str = Field(min_length=1, max_length=2048)
    signature_path: str | None = Field(default=None, max_length=2048)
    trust_local_keys: bool = True


class BackupCreateRequest(BaseModel):
    password: str = Field(min_length=8, max_length=4096)


class BackupRestoreRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    password: str = Field(min_length=1, max_length=4096)
    folder: str = Field(min_length=1, max_length=240)


class CharacterCardImportRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    folder: str = Field(min_length=1, max_length=240)
    persona_id: str | None = Field(default=None, max_length=80)
    locale: str = Field(default="zh-CN", min_length=2, max_length=32)


class CharacterCardExportRequest(BaseModel):
    version: Literal[2, 3] = 3
    charx: bool = False


class AdapterDoctorRequest(BaseModel):
    container: str | None = Field(default=None, max_length=240)
    ssh_host: str | None = Field(default=None, max_length=240)


class SkillRequest(BaseModel):
    target: Literal["codex", "claude", "opencode", "agents", "generic"]
    scope: Literal["project", "global"] = "global"
    persona_id: str | None = None


def _store() -> ArtifactStore:
    return ArtifactStore()


def _jobs() -> JobStore:
    return JobStore()


def _paths() -> PersonaPathPolicy:
    return PersonaPathPolicy()


def _service(
    registry_factory: Callable[[], RegistryService],
    store_factory: Callable[[], ArtifactStore],
) -> ArtifactApplicationService:
    return ArtifactApplicationService(registry_factory(), store_factory())


def _run_job(
    store: JobStore,
    *,
    kind: str,
    label: str,
    input: dict[str, Any],
    operation: Callable[[], dict[str, Any]],
    persona_id: str | None = None,
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


def _raise_http(error: Exception) -> None:
    if isinstance(error, FileNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, (ArtifactPathError, WebPathError)):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, FileExistsError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(
        error,
        (
            CharacterCardError,
            PackageTrustError,
            PrivateBackupError,
            KeyError,
            ValueError,
            OSError,
        ),
    ):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


def register_artifact_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], RegistryService],
    store_factory: Callable[[], ArtifactStore] = _store,
    job_store_factory: Callable[[], JobStore] = _jobs,
    path_policy_factory: Callable[[], PersonaPathPolicy] = _paths,
) -> None:
    @app.get("/api/v1/artifacts")
    def artifacts(
        category: Literal["uploads", "exports", "backups", "keys"] = "exports",
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = store_factory()
        values = store.list(category)
        if category == "keys":
            # Private keys are intentionally absent from generic file listings.
            values = [item for item in values if item["name"].endswith(".pub")]
        return {
            "category": category,
            "roots": store.roots.to_dict(),
            "items": values,
            "count": len(values),
        }

    @app.post("/api/v1/uploads", status_code=201)
    def upload(
        request: UploadRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            path = store_factory().upload_base64(request.filename, request.content_base64)
            return {"name": path.name, "path": str(path), "size": path.stat().st_size}
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.get("/api/v1/artifacts/download")
    def download_artifact(
        path: str = Query(min_length=1, max_length=2048),
        _: None = Depends(require_token),
    ) -> FileResponse:
        try:
            resolved = store_factory().resolve(
                path,
                categories=("uploads", "exports", "backups", "keys"),
            )
            if resolved.parent == store_factory().roots.keys and not resolved.name.endswith(".pub"):
                raise ArtifactPathError("private signing keys cannot be downloaded")
            return FileResponse(resolved, filename=resolved.name)
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/personas/{persona_id}/builds")
    def build_persona(
        persona_id: str,
        request: BuildRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = _service(registry_factory, store_factory)
            return _run_job(
                job_store_factory(),
                kind="persona.build",
                label="构建 Persona 目标产物",
                input={"persona_id": persona_id, "targets": request.targets},
                persona_id=persona_id,
                operation=lambda: service.build(persona_id, targets=request.targets),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/personas/{persona_id}/packages")
    def pack_persona(
        persona_id: str,
        request: BuildRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = _service(registry_factory, store_factory)
            return _run_job(
                job_store_factory(),
                kind="persona.pack",
                label="创建 PersonaPack",
                input={"persona_id": persona_id, "targets": request.targets},
                persona_id=persona_id,
                operation=lambda: service.pack(persona_id, targets=request.targets),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/personas/{persona_id}/public-export")
    def public_export(
        persona_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = _service(registry_factory, store_factory)
            return _run_job(
                job_store_factory(),
                kind="persona.export-public",
                label="导出公开 Persona 工程",
                input={"persona_id": persona_id},
                persona_id=persona_id,
                operation=lambda: service.public_export(persona_id),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/packages/inspect")
    def inspect_persona_package(
        request: ArtifactPathRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return _service(registry_factory, store_factory).inspect_package(request.path)
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.get("/api/v1/trust/keys")
    def signing_keys(_: None = Depends(require_token)) -> dict[str, Any]:
        values = _service(registry_factory, store_factory).list_keys()
        return {"items": values, "count": len(values)}

    @app.post("/api/v1/trust/keys", status_code=201)
    def create_signing_key(
        request: KeyCreateRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return _service(registry_factory, store_factory).create_key(request.name)
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/trust/signatures")
    def sign_persona_package(
        request: SignRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = _service(registry_factory, store_factory)
            return _run_job(
                job_store_factory(),
                kind="trust.sign",
                label="签名 PersonaPack",
                input={"package_path": request.package_path, "key_id": request.key_id},
                operation=lambda: service.sign(request.package_path, key_id=request.key_id),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/trust/verify")
    def verify_persona_package(
        request: VerifyRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = _service(registry_factory, store_factory)
            return _run_job(
                job_store_factory(),
                kind="trust.verify",
                label="验证 PersonaPack",
                input={
                    "package_path": request.package_path,
                    "signature_path": request.signature_path,
                    "trust_local_keys": request.trust_local_keys,
                },
                operation=lambda: service.verify(
                    request.package_path,
                    signature_path=request.signature_path,
                    trust_local_keys=request.trust_local_keys,
                ),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/personas/{persona_id}/backups")
    def create_backup(
        persona_id: str,
        request: BackupCreateRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = _service(registry_factory, store_factory)
            # Password is intentionally excluded from Job input and output.
            return _run_job(
                job_store_factory(),
                kind="backup.create",
                label="创建加密私有备份",
                input={"persona_id": persona_id},
                persona_id=persona_id,
                operation=lambda: service.create_backup(persona_id, password=request.password),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/backups/inspect")
    def inspect_backup(
        request: ArtifactPathRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return _service(registry_factory, store_factory).inspect_backup(request.path)
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/backups/restore")
    def restore_backup(
        request: BackupRestoreRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            destination = path_policy_factory().resolve_new(request.folder)
            service = _service(registry_factory, store_factory)
            return _run_job(
                job_store_factory(),
                kind="backup.restore",
                label="恢复加密私有备份",
                input={"path": request.path, "folder": request.folder},
                operation=lambda: service.restore_backup(
                    request.path,
                    destination,
                    password=request.password,
                ),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/character-cards/inspect")
    def inspect_character_card(
        request: ArtifactPathRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return _service(registry_factory, store_factory).inspect_character_card(request.path)
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/character-cards/import")
    def import_card(
        request: CharacterCardImportRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            destination = path_policy_factory().resolve_new(request.folder)
            service = _service(registry_factory, store_factory)
            return _run_job(
                job_store_factory(),
                kind="character-card.import",
                label="导入 Character Card",
                input={
                    "path": request.path,
                    "folder": request.folder,
                    "persona_id": request.persona_id,
                    "locale": request.locale,
                },
                operation=lambda: service.import_character_card(
                    request.path,
                    destination,
                    persona_id=request.persona_id,
                    locale=request.locale,
                ),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/personas/{persona_id}/character-card")
    def export_card(
        persona_id: str,
        request: CharacterCardExportRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = _service(registry_factory, store_factory)
            return _run_job(
                job_store_factory(),
                kind="character-card.export",
                label="导出 Character Card",
                input={
                    "persona_id": persona_id,
                    "version": request.version,
                    "charx": request.charx,
                },
                persona_id=persona_id,
                operation=lambda: service.export_character_card(
                    persona_id,
                    version=request.version,
                    charx=request.charx,
                ),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.get("/api/v1/adapters")
    def adapters(_: None = Depends(require_token)) -> dict[str, Any]:
        return _service(registry_factory, store_factory).adapter_summary()

    @app.get("/api/v1/adapters/{adapter_name}")
    def adapter(
        adapter_name: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            return _service(registry_factory, store_factory).adapter(adapter_name)
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/adapters/{adapter_name}/doctor")
    def adapter_doctor(
        adapter_name: str,
        request: AdapterDoctorRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = _service(registry_factory, store_factory)
            return _run_job(
                job_store_factory(),
                kind="adapter.doctor",
                label=f"检查 Adapter：{adapter_name}",
                input=request.model_dump(),
                operation=lambda: service.adapter_doctor(
                    adapter_name,
                    container=request.container,
                    ssh_host=request.ssh_host,
                ),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.get("/api/v1/skills")
    def skills(_: None = Depends(require_token)) -> dict[str, Any]:
        return {"targets": sorted(SKILL_TARGETS), "scopes": ["global", "project"]}

    @app.post("/api/v1/skills/plan")
    def skill_plan(
        request: SkillRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = _service(registry_factory, store_factory)
            project_root = (
                service.persona_root(request.persona_id)
                if request.scope == "project" and request.persona_id
                else None
            )
            return service.skill_plan(
                request.target,
                scope=request.scope,
                project_root=project_root,
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/skills/install")
    def install_persona_skill(
        request: SkillRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            service = _service(registry_factory, store_factory)
            project_root = (
                service.persona_root(request.persona_id)
                if request.scope == "project" and request.persona_id
                else None
            )
            return _run_job(
                job_store_factory(),
                kind="skill.install",
                label=f"安装 persona-builder：{request.target}",
                input={
                    "target": request.target,
                    "scope": request.scope,
                    "persona_id": request.persona_id,
                },
                persona_id=request.persona_id,
                operation=lambda: service.install_persona_skill(
                    request.target,
                    scope=request.scope,
                    project_root=project_root,
                ),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")


__all__ = ["register_artifact_routes"]
