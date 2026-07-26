from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from persona_dock.application.personas import PersonaApplicationService
from persona_dock.application.revisions import RevisionStore, canonical_hash
from persona_dock.compiler import compile_project
from persona_dock.core.models import load_canonical_persona, normalize_canonical_persona
from persona_dock.core.testing import run_persona_tests
from persona_dock.io import dump_yaml, load_yaml
from persona_dock.project import PROJECT_FILE, init_project, validate_project
from persona_dock.registry import RegistryService
from persona_dock.registry.database import registry_root

from .providers import ProviderClient


GENERATION_MODES = {"create", "refine", "distill", "hybrid"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        result = dict(base)
        for key, value in overlay.items():
            result[key] = _merge(result[key], value) if key in result else value
        return result
    return overlay


def _json_object(content: str) -> dict[str, Any]:
    value = content.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model output does not contain a JSON object")
        payload = json.loads(value[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("model output must be a JSON object")
    return payload


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    id: str
    status: str
    mode: str
    provider_id: str
    persona_id: str | None
    requested_persona_id: str | None
    requested_name: str | None
    locale: str
    prompt_hash: str
    base_hash: str | None
    draft: dict[str, Any]
    diff: dict[str, Any]
    validation: dict[str, Any]
    tests: dict[str, Any]
    compile_preview: dict[str, Any]
    usage: dict[str, Any]
    error: str | None
    applied_persona_id: str | None
    revision_id: str | None
    created_at: str
    updated_at: str
    applied_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_generations (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    persona_id TEXT,
    requested_persona_id TEXT,
    requested_name TEXT,
    locale TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    base_hash TEXT,
    draft_json TEXT NOT NULL,
    diff_json TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    tests_json TEXT NOT NULL,
    compile_json TEXT NOT NULL,
    usage_json TEXT NOT NULL,
    error TEXT,
    applied_persona_id TEXT,
    revision_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    applied_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_generations_created
    ON ai_generations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_generations_persona
    ON ai_generations(persona_id, created_at DESC);
"""


class GenerationStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path).expanduser().resolve()
            if path is not None
            else (registry_root() / "control-plane.db").resolve()
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> GenerationRecord:
        return GenerationRecord(
            id=str(row["id"]),
            status=str(row["status"]),
            mode=str(row["mode"]),
            provider_id=str(row["provider_id"]),
            persona_id=row["persona_id"],
            requested_persona_id=row["requested_persona_id"],
            requested_name=row["requested_name"],
            locale=str(row["locale"]),
            prompt_hash=str(row["prompt_hash"]),
            base_hash=row["base_hash"],
            draft=_load(row["draft_json"], {}),
            diff=_load(row["diff_json"], {}),
            validation=_load(row["validation_json"], {}),
            tests=_load(row["tests_json"], {}),
            compile_preview=_load(row["compile_json"], {}),
            usage=_load(row["usage_json"], {}),
            error=row["error"],
            applied_persona_id=row["applied_persona_id"],
            revision_id=row["revision_id"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            applied_at=row["applied_at"],
        )

    def create_pending(
        self,
        *,
        mode: str,
        provider_id: str,
        persona_id: str | None,
        requested_persona_id: str | None,
        requested_name: str | None,
        locale: str,
        prompt_hash: str,
        base_hash: str | None,
    ) -> GenerationRecord:
        generation_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_generations(
                    id, status, mode, provider_id, persona_id,
                    requested_persona_id, requested_name, locale, prompt_hash,
                    base_hash, draft_json, diff_json, validation_json,
                    tests_json, compile_json, usage_json, created_at, updated_at
                ) VALUES(?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', '{}', '{}', '{}', ?, ?)
                """,
                (
                    generation_id,
                    mode,
                    provider_id,
                    persona_id,
                    requested_persona_id,
                    requested_name,
                    locale,
                    prompt_hash,
                    base_hash,
                    now,
                    now,
                ),
            )
        result = self.get(generation_id)
        assert result is not None
        return result

    def finish(
        self,
        generation_id: str,
        *,
        draft: dict[str, Any],
        diff: dict[str, Any],
        validation: dict[str, Any],
        tests: dict[str, Any],
        compile_preview: dict[str, Any],
        usage: dict[str, Any],
    ) -> GenerationRecord:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ai_generations SET
                    status = 'draft', draft_json = ?, diff_json = ?,
                    validation_json = ?, tests_json = ?, compile_json = ?,
                    usage_json = ?, error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    _dump(draft),
                    _dump(diff),
                    _dump(validation),
                    _dump(tests),
                    _dump(compile_preview),
                    _dump(usage),
                    utc_now(),
                    generation_id,
                ),
            )
        result = self.get(generation_id)
        assert result is not None
        return result

    def fail(self, generation_id: str, error: str) -> GenerationRecord:
        with self._connect() as connection:
            connection.execute(
                "UPDATE ai_generations SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                (error[:4000], utc_now(), generation_id),
            )
        result = self.get(generation_id)
        assert result is not None
        return result

    def applied(
        self,
        generation_id: str,
        *,
        persona_id: str,
        revision_id: str,
    ) -> GenerationRecord:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ai_generations SET
                    status = 'applied', applied_persona_id = ?, revision_id = ?,
                    applied_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (persona_id, revision_id, now, now, generation_id),
            )
        result = self.get(generation_id)
        assert result is not None
        return result

    def get(self, generation_id: str) -> GenerationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ai_generations WHERE id = ?",
                (generation_id,),
            ).fetchone()
        return self._record(row) if row else None

    def list(self, *, limit: int = 100) -> list[GenerationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ai_generations ORDER BY created_at DESC, id DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [self._record(row) for row in rows]


class AIPersonaStudio:
    SYSTEM_PROMPT = """You are PersonaDock's Canonical Persona v3 compiler.
Return exactly one complete JSON object and no commentary.
The JSON must preserve schema_version 3 and be suitable for PersonaDock validation.
Never invent memories, shared history, relationships, private facts, credentials, or user preferences not explicitly supplied.
Observed chat evidence is uncertain evidence, not a fact. Mark inferred rules with source_type observed-evidence and conservative confidence.
Explicit user design overrides observations. Boundaries and privacy rules must not be weakened silently.
Keep raw chat text out of the persona. Evidence entries should be short labels, not copied transcripts.
Use only these source_type values: explicit-design, observed-evidence, reviewed-existing, safe-default.
Use only these priorities: low, medium, high, critical.
Use only these confidence values: explicit, high, medium, low.
"""

    def __init__(
        self,
        providers: ProviderClient,
        registry: RegistryService | None = None,
        generations: GenerationStore | None = None,
        revisions: RevisionStore | None = None,
    ) -> None:
        self.providers = providers
        self.registry = registry or RegistryService()
        self.generations = generations or GenerationStore()
        self.revisions = revisions or RevisionStore()

    @staticmethod
    def _template(persona_id: str, name: str, locale: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="personadock-ai-template-") as directory:
            root = init_project(
                Path(directory) / "persona",
                persona_id,
                name,
                locale=locale,
                force=False,
                schema_version=3,
            )
            return normalize_canonical_persona(load_yaml(root / PROJECT_FILE))

    def _existing(self, persona_id: str) -> tuple[Path, dict[str, Any]]:
        record = self.registry.get_persona(persona_id)
        if record is None or not record.source_path:
            raise KeyError(f"persona is not registered: {persona_id}")
        root = Path(record.source_path).expanduser().resolve()
        return root, load_canonical_persona(root)

    @staticmethod
    def _evaluation(model: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="personadock-ai-evaluate-") as directory:
            root = init_project(
                Path(directory) / "persona",
                str(model["id"]),
                str(model["name"]),
                locale=str(model.get("locale") or "zh-CN"),
                force=False,
                schema_version=3,
            )
            (root / PROJECT_FILE).write_text(dump_yaml(model), encoding="utf-8")
            errors = validate_project(root)
            validation = {"valid": not errors, "errors": errors}
            if errors:
                raise ValueError("generated persona validation failed: " + "; ".join(errors))
            tests = run_persona_tests(root).to_dict()
            build = compile_project(root)
            manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
            previews: dict[str, str] = {}
            for relative in (
                "targets/hermes/SOUL.md",
                "targets/openclaw/SOUL.md",
                "targets/generic/system-prompt.md",
            ):
                path = build / relative
                if path.is_file():
                    previews[relative] = path.read_text(encoding="utf-8")
            compile_preview = {
                "manifest": manifest,
                "files": previews,
            }
            return validation, tests, compile_preview

    @staticmethod
    def _user_prompt(
        *,
        mode: str,
        instruction: str,
        evidence: str,
        base_model: dict[str, Any],
    ) -> str:
        sections = [
            f"Mode: {mode}",
            "User instruction:",
            instruction.strip(),
            "Current/template Canonical Persona JSON:",
            json.dumps(base_model, ensure_ascii=False, indent=2, sort_keys=True),
        ]
        if evidence.strip():
            sections.extend(
                [
                    "User-provided evidence for this one generation only:",
                    evidence.strip(),
                    "Do not reproduce the transcript. Distill only reviewable rules supported by the supplied evidence.",
                ]
            )
        sections.append("Return the complete updated Canonical Persona v3 JSON object.")
        return "\n\n".join(sections)

    def generate(
        self,
        *,
        provider_id: str,
        mode: str,
        instruction: str,
        evidence: str = "",
        persona_id: str | None = None,
        requested_persona_id: str | None = None,
        requested_name: str | None = None,
        locale: str = "zh-CN",
    ) -> GenerationRecord:
        resolved_mode = mode.strip().lower()
        if resolved_mode not in GENERATION_MODES:
            raise ValueError(f"unsupported AI generation mode: {mode}")
        if not instruction.strip():
            raise ValueError("AI generation instruction cannot be empty")
        if len(instruction) > 50000 or len(evidence) > 200000:
            raise ValueError("AI generation input is too large")

        existing = bool(persona_id)
        if resolved_mode == "refine" and not existing:
            raise ValueError("refine mode requires an existing persona")
        if existing:
            _, base_model = self._existing(str(persona_id))
            target_id = str(base_model["id"])
            target_name = str(base_model["name"])
            resolved_locale = str(base_model.get("locale") or locale)
            base_hash = canonical_hash(base_model)
        else:
            target_id = (requested_persona_id or "").strip()
            target_name = (requested_name or "").strip()
            if not target_id or not target_name:
                raise ValueError("new AI persona requires ID and name")
            resolved_locale = locale.strip() or "zh-CN"
            base_model = self._template(target_id, target_name, resolved_locale)
            base_hash = None

        prompt = self._user_prompt(
            mode=resolved_mode,
            instruction=instruction,
            evidence=evidence,
            base_model=base_model,
        )
        prompt_hash = _hash_text(self.SYSTEM_PROMPT + "\n" + prompt)
        pending = self.generations.create_pending(
            mode=resolved_mode,
            provider_id=provider_id,
            persona_id=persona_id,
            requested_persona_id=target_id if not existing else None,
            requested_name=target_name if not existing else None,
            locale=resolved_locale,
            prompt_hash=prompt_hash,
            base_hash=base_hash,
        )
        try:
            response = self.providers.generate(
                provider_id,
                system=self.SYSTEM_PROMPT,
                prompt=prompt,
            )
            generated = _json_object(str(response["content"]))
            draft = normalize_canonical_persona(_merge(base_model, generated))
            draft["id"] = target_id
            draft["name"] = target_name if existing else str(draft.get("name") or target_name)
            draft["locale"] = resolved_locale
            draft["schema_version"] = 3
            draft = normalize_canonical_persona(draft)
            validation, tests, compile_preview = self._evaluation(draft)
            diff = self.revisions.diff(base_model, draft)
            return self.generations.finish(
                pending.id,
                draft=draft,
                diff=diff,
                validation=validation,
                tests=tests,
                compile_preview=compile_preview,
                usage=response.get("usage") if isinstance(response.get("usage"), dict) else {},
            )
        except Exception as error:
            self.generations.fail(pending.id, str(error))
            raise

    @staticmethod
    def _atomic_model_write(root: Path, model: dict[str, Any]) -> bytes:
        project_file = root / PROJECT_FILE
        original = project_file.read_bytes()
        fd, temporary_name = tempfile.mkstemp(
            prefix="ai-persona-",
            suffix=".yaml",
            dir=root,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(dump_yaml(model))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, project_file)
        finally:
            temporary.unlink(missing_ok=True)
        return original

    def apply(
        self,
        generation_id: str,
        *,
        destination: Path | None = None,
    ) -> GenerationRecord:
        record = self.generations.get(generation_id)
        if record is None:
            raise KeyError(generation_id)
        if record.status != "draft":
            raise ValueError(f"AI generation cannot be applied: {record.status}")
        draft = normalize_canonical_persona(record.draft)
        service = PersonaApplicationService(self.registry)

        if record.persona_id:
            root, current = self._existing(record.persona_id)
            if record.base_hash and canonical_hash(current) != record.base_hash:
                raise ValueError("persona changed after AI generation; generate a new draft")
            latest = self.revisions.latest(record.persona_id)
            if latest is None or latest.content_hash != canonical_hash(current):
                self.revisions.capture(
                    record.persona_id,
                    current,
                    source="ai-refine-base",
                    summary="Base revision captured before AI refinement",
                )
            original = self._atomic_model_write(root, draft)
            errors = validate_project(root)
            if errors:
                (root / PROJECT_FILE).write_bytes(original)
                raise ValueError("AI draft validation failed during apply: " + "; ".join(errors))
            service.register(root)
            revision = self.revisions.capture(
                record.persona_id,
                draft,
                source=f"ai-{record.mode}",
                summary="Reviewed AI Persona draft applied from Web Studio",
                validation_result=record.validation,
                test_result=record.tests,
            )
            self.registry.journal(
                "ai-persona-applied",
                persona_id=record.persona_id,
                payload={
                    "generation_id": record.id,
                    "provider_id": record.provider_id,
                    "prompt_hash": record.prompt_hash,
                    "revision_id": revision.revision_id,
                },
            )
            return self.generations.applied(
                record.id,
                persona_id=record.persona_id,
                revision_id=revision.revision_id,
            )

        if destination is None:
            raise ValueError("new AI persona requires a destination")
        created = service.create(
            destination,
            persona_id=str(draft["id"]),
            name=str(draft["name"]),
            locale=str(draft.get("locale") or record.locale),
        )
        root = Path(created["project"])
        original = self._atomic_model_write(root, draft)
        errors = validate_project(root)
        if errors:
            (root / PROJECT_FILE).write_bytes(original)
            raise ValueError("AI draft validation failed during apply: " + "; ".join(errors))
        service.register(root)
        revision = self.revisions.capture(
            str(draft["id"]),
            draft,
            source=f"ai-{record.mode}",
            summary="Reviewed AI Persona draft created from Web Studio",
            validation_result=record.validation,
            test_result=record.tests,
        )
        self.registry.journal(
            "ai-persona-created",
            persona_id=str(draft["id"]),
            payload={
                "generation_id": record.id,
                "provider_id": record.provider_id,
                "prompt_hash": record.prompt_hash,
                "revision_id": revision.revision_id,
            },
        )
        return self.generations.applied(
            record.id,
            persona_id=str(draft["id"]),
            revision_id=revision.revision_id,
        )

    def get(self, generation_id: str) -> GenerationRecord | None:
        return self.generations.get(generation_id)

    def list(self, *, limit: int = 100) -> list[GenerationRecord]:
        return self.generations.list(limit=limit)


__all__ = [
    "AIPersonaStudio",
    "GENERATION_MODES",
    "GenerationRecord",
    "GenerationStore",
]
