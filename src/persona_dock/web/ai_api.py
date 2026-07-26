from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

from persona_dock.ai import AIPersonaStudio, GenerationStore, ProviderClient, ProviderStore, SecretVault
from persona_dock.ai.providers import ProviderRequestError
from persona_dock.ai.secrets import SecretVaultError
from persona_dock.registry import RegistryService

from .jobs import JobStore
from .paths import PersonaPathPolicy, WebPathError


ProviderKind = Literal["openai", "openai-compatible", "anthropic", "gemini", "ollama"]
GenerationMode = Literal["create", "refine", "distill", "hybrid"]


class ProviderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: ProviderKind
    base_url: str | None = Field(default=None, max_length=2048)
    model: str = Field(min_length=1, max_length=240)
    temperature: float = Field(default=0.4, ge=0, le=2)
    max_output_tokens: int = Field(default=4096, ge=64, le=131072)
    timeout_seconds: int = Field(default=90, ge=1, le=600)
    structured_output: bool = True
    api_key: str | None = Field(default=None, max_length=8192)
    headers: dict[str, str] = Field(default_factory=dict)


class ProviderUpdateRequest(ProviderCreateRequest):
    clear_secret: bool = False


class GenerationRequest(BaseModel):
    provider_id: str = Field(min_length=1, max_length=120)
    mode: GenerationMode
    instruction: str = Field(min_length=1, max_length=50000)
    evidence: str = Field(default="", max_length=200000)
    persona_id: str | None = Field(default=None, max_length=120)
    requested_persona_id: str | None = Field(default=None, max_length=80)
    requested_name: str | None = Field(default=None, max_length=160)
    locale: str = Field(default="zh-CN", min_length=2, max_length=32)


class GenerationApplyRequest(BaseModel):
    confirmation: Literal["APPLY"]
    folder: str | None = Field(default=None, max_length=240)


def _jobs() -> JobStore:
    return JobStore()


def _providers() -> ProviderStore:
    return ProviderStore(vault=SecretVault())


def _paths() -> PersonaPathPolicy:
    return PersonaPathPolicy()


def _studio(
    registry_factory: Callable[[], RegistryService],
    provider_store: ProviderStore,
) -> AIPersonaStudio:
    return AIPersonaStudio(
        ProviderClient(provider_store),
        registry_factory(),
        GenerationStore(provider_store.path),
    )


def _public(provider_store: ProviderStore, value: Any) -> dict[str, Any]:
    return value.to_dict(vault=provider_store.vault)


def _raise_http(error: Exception) -> None:
    if isinstance(error, KeyError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, WebPathError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, (ProviderRequestError, SecretVaultError)):
        raise HTTPException(status_code=502, detail=str(error)) from error
    if isinstance(error, (ValueError, FileExistsError, OSError)):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


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


def register_ai_routes(
    app: FastAPI,
    require_token: Callable[..., None],
    registry_factory: Callable[[], RegistryService],
    provider_store_factory: Callable[[], ProviderStore] = _providers,
    path_policy_factory: Callable[[], PersonaPathPolicy] = _paths,
    job_store_factory: Callable[[], JobStore] = _jobs,
    studio_factory: Callable[[ProviderStore], AIPersonaStudio] | None = None,
) -> None:
    def studio(store: ProviderStore) -> AIPersonaStudio:
        return studio_factory(store) if studio_factory else _studio(registry_factory, store)

    @app.get("/api/v1/ai/providers")
    def providers(_: None = Depends(require_token)) -> dict[str, Any]:
        store = provider_store_factory()
        values = [_public(store, item) for item in store.list()]
        return {"items": values, "count": len(values)}

    @app.post("/api/v1/ai/providers", status_code=201)
    def create_provider(
        request: ProviderCreateRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = provider_store_factory()
        try:
            value = store.create(**request.model_dump())
            return _public(store, value)
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.put("/api/v1/ai/providers/{provider_id}")
    def update_provider(
        provider_id: str,
        request: ProviderUpdateRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = provider_store_factory()
        try:
            value = store.update(provider_id, **request.model_dump())
            return _public(store, value)
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.delete("/api/v1/ai/providers/{provider_id}", status_code=204)
    def delete_provider(
        provider_id: str,
        _: None = Depends(require_token),
    ) -> Response:
        store = provider_store_factory()
        if not store.delete(provider_id):
            raise HTTPException(status_code=404, detail="provider not found")
        return Response(status_code=204)

    @app.post("/api/v1/ai/providers/{provider_id}/test")
    def test_provider(
        provider_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = provider_store_factory()
        try:
            return ProviderClient(store).test(provider_id)
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.get("/api/v1/ai/providers/{provider_id}/models")
    def provider_models(
        provider_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = provider_store_factory()
        try:
            values = ProviderClient(store).list_models(provider_id)
            return {"items": values, "count": len(values)}
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.get("/api/v1/ai/generations")
    def generations(
        limit: int = Query(default=100, ge=1, le=200),
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = provider_store_factory()
        values = [item.to_dict() for item in studio(store).list(limit=limit)]
        return {"items": values, "count": len(values)}

    @app.get("/api/v1/ai/generations/{generation_id}")
    def generation(
        generation_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = provider_store_factory()
        value = studio(store).get(generation_id)
        if value is None:
            raise HTTPException(status_code=404, detail="generation not found")
        return value.to_dict()

    @app.post("/api/v1/ai/generations", status_code=201)
    def create_generation(
        request: GenerationRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = provider_store_factory()
        service = studio(store)
        request_hash = hashlib.sha256(
            (request.instruction + "\x1f" + request.evidence).encode("utf-8")
        ).hexdigest()
        try:
            return _run_job(
                job_store_factory(),
                kind="ai.generate",
                label="生成 Persona 草稿",
                persona_id=request.persona_id,
                input={
                    "provider_id": request.provider_id,
                    "mode": request.mode,
                    "persona_id": request.persona_id,
                    "requested_persona_id": request.requested_persona_id,
                    "input_hash": request_hash,
                },
                operation=lambda: service.generate(**request.model_dump()).to_dict(),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")

    @app.post("/api/v1/ai/generations/{generation_id}/apply")
    def apply_generation(
        generation_id: str,
        request: GenerationApplyRequest,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        store = provider_store_factory()
        service = studio(store)
        current = service.get(generation_id)
        if current is None:
            raise HTTPException(status_code=404, detail="generation not found")
        try:
            destination = None
            if current.persona_id is None:
                folder = request.folder or current.requested_persona_id or generation_id
                destination = path_policy_factory().resolve_new(folder)
            return _run_job(
                job_store_factory(),
                kind="ai.apply",
                label="应用已审核 AI Persona 草稿",
                persona_id=current.persona_id or current.requested_persona_id,
                input={"generation_id": generation_id},
                operation=lambda: service.apply(
                    generation_id,
                    destination=destination,
                ).to_dict(),
            )
        except Exception as error:
            _raise_http(error)
            raise AssertionError("unreachable")


__all__ = [
    "GenerationApplyRequest",
    "GenerationRequest",
    "ProviderCreateRequest",
    "ProviderUpdateRequest",
    "register_ai_routes",
]
