from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from persona_dock.io import dump_yaml, load_yaml
from persona_dock.project import PROJECT_FILE, init_project, validate_project
from persona_dock.registry.database import registry_root
from persona_dock.registry.models import RuntimeInstanceRecord
from persona_dock.registry.service import RegistryService


class AdoptionError(ValueError):
    """Raised when an existing runtime persona cannot be adopted safely."""


@dataclass(frozen=True)
class SnapshotResult:
    id: str
    instance_id: str
    path: str
    file_count: int
    manifest_path: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdoptionDraft:
    persona_id: str
    name: str
    instance_id: str
    adapter: str
    destination: str
    snapshot: SnapshotResult
    selected_skill: str | None
    imported_skills: tuple[str, ...]
    memory_candidates: int
    preserved_files: tuple[str, ...]
    excluded_files: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["snapshot"] = self.snapshot.to_dict()
        return value


_SECRET_NAMES = {
    ".env",
    "auth.json",
    "credentials.json",
    "secrets.json",
    "tokens.json",
}
_SECRET_PARTS = {"sessions", "session", "logs", "cache", "tmp", "credentials", "auth"}

_HERMES_SNAPSHOT_PATHS = (
    "SOUL.md",
    "config.yaml",
    "skills",
    "memories/MEMORY.md",
    "memories/USER.md",
)

_OPENCLAW_SNAPSHOT_PATHS = (
    "SOUL.md",
    "IDENTITY.md",
    "AGENTS.md",
    "USER.md",
    "TOOLS.md",
    "MEMORY.md",
    "skills",
    "memory",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not normalized:
        normalized = "imported-persona"
    if not normalized[0].isalnum():
        normalized = "persona-" + normalized
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_secret_or_runtime(relative: Path) -> bool:
    lowered = {part.lower() for part in relative.parts}
    return relative.name.lower() in _SECRET_NAMES or bool(lowered & _SECRET_PARTS)


def _iter_selected_files(root: Path, adapter: str) -> tuple[list[Path], list[str]]:
    selected = _HERMES_SNAPSHOT_PATHS if adapter == "hermes" else _OPENCLAW_SNAPSHOT_PATHS
    files: list[Path] = []
    excluded: list[str] = []
    for value in selected:
        candidate = root / value
        if candidate.is_file():
            relative = candidate.relative_to(root)
            if _is_secret_or_runtime(relative):
                excluded.append(relative.as_posix())
            else:
                files.append(candidate)
        elif candidate.is_dir():
            for path in sorted(item for item in candidate.rglob("*") if item.is_file()):
                relative = path.relative_to(root)
                if _is_secret_or_runtime(relative):
                    excluded.append(relative.as_posix())
                else:
                    files.append(path)
    return files, excluded


def _record_snapshot(
    service: RegistryService,
    instance: RuntimeInstanceRecord,
    snapshot_id: str,
    path: Path,
    metadata: dict[str, Any],
    created_at: str,
) -> None:
    with service.database.session() as connection:
        connection.execute(
            """
            INSERT INTO snapshots(
                id, persona_id, runtime_instance_id, kind, path,
                metadata_json, created_at
            ) VALUES(?, NULL, ?, 'pre-adoption', ?, ?, ?)
            """,
            (
                snapshot_id,
                instance.id,
                str(path),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                created_at,
            ),
        )
    service.journal(
        "runtime-instance-snapshotted",
        runtime_instance_id=instance.id,
        payload={"snapshot_id": snapshot_id, "path": str(path), "kind": "pre-adoption"},
    )


def snapshot_runtime_instance(
    instance: RuntimeInstanceRecord,
    *,
    registry: RegistryService | None = None,
) -> SnapshotResult:
    service = registry or RegistryService()
    source = Path(instance.location).expanduser().resolve()
    if not source.is_dir():
        raise AdoptionError(f"runtime instance directory does not exist: {source}")
    if instance.adapter not in {"hermes", "openclaw"}:
        raise AdoptionError(f"unsupported adoption adapter: {instance.adapter}")

    snapshot_id = str(uuid.uuid4())
    created_at = _utc_now()
    destination = (
        registry_root()
        / "snapshots"
        / instance.adapter
        / _safe_id(instance.platform_instance_id)
        / f"{_timestamp()}-{snapshot_id[:8]}"
    )
    content_root = destination / "content"
    content_root.mkdir(parents=True, exist_ok=False)

    selected, excluded = _iter_selected_files(source, instance.adapter)
    manifest_files: list[dict[str, Any]] = []
    for path in selected:
        relative = path.relative_to(source)
        target = content_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        manifest_files.append(
            {
                "path": relative.as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    manifest = {
        "format": "personadock-runtime-snapshot",
        "format_version": 1,
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "read_only_source": True,
        "instance": instance.to_dict(),
        "files": manifest_files,
        "excluded": sorted(set(excluded)),
        "never_included": sorted(_SECRET_NAMES | _SECRET_PARTS),
    }
    manifest_path = destination / "snapshot-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _record_snapshot(service, instance, snapshot_id, destination, manifest, created_at)
    return SnapshotResult(
        id=snapshot_id,
        instance_id=instance.id,
        path=str(destination),
        file_count=len(manifest_files),
        manifest_path=str(manifest_path),
        created_at=created_at,
    )


def _first_heading_or_text(path: Path, fallback: str) -> str:
    if not path.is_file():
        return fallback
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    for line in text.splitlines():
        if line.strip().startswith("#"):
            value = line.strip().lstrip("#").strip()
            if value:
                return value
    return text[:120] or fallback


def _skill_directories(source: Path) -> list[Path]:
    root = source / "skills"
    if not root.is_dir():
        return []
    return sorted(
        child
        for child in root.iterdir()
        if child.is_dir() and (child / "SKILL.md").is_file()
    )


def _select_persona_skill(skills: list[Path], persona_id: str) -> Path | None:
    if not skills:
        return None
    persona_tokens = {persona_id, f"{persona_id}-persona", "persona"}
    for skill in skills:
        if skill.name.lower() in persona_tokens or "persona" in skill.name.lower():
            return skill
    return skills[0] if len(skills) == 1 else None


def _memory_documents(source: Path, adapter: str) -> list[Path]:
    candidates: list[Path] = []
    if adapter == "hermes":
        for relative in ("memories/MEMORY.md", "memories/USER.md"):
            path = source / relative
            if path.is_file():
                candidates.append(path)
    else:
        for relative in ("MEMORY.md", "USER.md"):
            path = source / relative
            if path.is_file():
                candidates.append(path)
        daily = source / "memory"
        if daily.is_dir():
            candidates.extend(sorted(path for path in daily.glob("*.md") if path.is_file()))
    return candidates


def _write_memory_candidates(
    project: Path,
    source: Path,
    instance: RuntimeInstanceRecord,
) -> int:
    output = project / ".private" / "memory-candidates.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as stream:
        for path in _memory_documents(source, instance.adapter):
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if not text:
                continue
            relative = path.relative_to(source).as_posix()
            record = {
                "id": str(uuid.uuid4()),
                "type": "imported-memory-document",
                "summary": text[:1000],
                "source": {
                    "adapter": instance.adapter,
                    "runtime_instance_id": instance.id,
                    "platform_instance_id": instance.platform_instance_id,
                    "path": relative,
                    "sha256": _sha256(path),
                },
                "reviewed": False,
                "sensitivity": "private",
                "sync_scope": "local-only",
                "status": "pending",
            }
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def _copy_imported_skills(
    project: Path,
    source: Path,
    selected: Path | None,
) -> tuple[str, ...]:
    skills = _skill_directories(source)
    imported_root = project / ".private" / "imported-skills"
    imported: list[str] = []
    for skill in skills:
        imported_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill, imported_root / skill.name, dirs_exist_ok=True)
        imported.append(skill.name)
    if selected is not None:
        canonical = project / "skills" / "persona"
        shutil.rmtree(canonical)
        shutil.copytree(selected, canonical)
    return tuple(imported)


def _update_project_metadata(
    project: Path,
    instance: RuntimeInstanceRecord,
    persona_id: str,
    name: str,
    soul_path: Path,
    selected_skill: Path | None,
) -> None:
    value = load_yaml(project / PROJECT_FILE)
    raw_soul = soul_path.read_text(encoding="utf-8", errors="replace").strip() if soul_path.is_file() else ""
    identity = raw_soul or f"你是{name}。该人格由现有 {instance.adapter} 实例接管生成，等待用户审核。"
    value["name"] = name
    value["summary"] = f"从 {instance.adapter}/{instance.platform_instance_id} 接管的人格草稿，尚需审核。"
    value["soul"]["identity"] = identity
    value["soul"]["core_traits"] = ["从现有人格导入", "等待结构化审核"]
    value["soul"]["voice"] = "保留导入人格的原始表达；在 Canonical Persona v3 迁移时进一步结构化。"
    value["skill"]["id"] = f"{persona_id}-persona"
    value["skill"]["description"] = (
        f"从现有 Skill `{selected_skill.name}` 导入的 {name} 人格规则。"
        if selected_skill
        else f"{name} 的待审核人格规则。"
    )
    (project / PROJECT_FILE).write_text(dump_yaml(value), encoding="utf-8")


def adoption_preview(
    instance_id: str,
    *,
    persona_id: str | None = None,
    name: str | None = None,
    destination: str | Path | None = None,
    registry: RegistryService | None = None,
) -> dict[str, Any]:
    service = registry or RegistryService()
    instance = service.get_runtime_instance(instance_id)
    if instance is None:
        raise AdoptionError(f"runtime instance is not registered: {instance_id}")
    resolved_id = _safe_id(persona_id or instance.platform_instance_id or instance.display_name)
    resolved_name = name or instance.display_name or instance.platform_instance_id
    resolved_destination = Path(destination).expanduser().resolve() if destination else registry_root() / "personas" / resolved_id
    existing = service.get_persona(resolved_id)
    source = Path(instance.location).expanduser().resolve()
    skills = _skill_directories(source)
    selected = _select_persona_skill(skills, resolved_id)
    memory = _memory_documents(source, instance.adapter)
    return {
        "instance": instance.to_dict(),
        "persona_id": resolved_id,
        "name": resolved_name,
        "destination": str(resolved_destination),
        "existing_persona": existing.to_dict() if existing else None,
        "selected_skill": selected.name if selected else None,
        "skills": [skill.name for skill in skills],
        "memory_documents": [path.relative_to(source).as_posix() for path in memory],
        "will_snapshot": True,
        "will_bind": True,
        "memory_policy": "pending-review-local-only",
        "excluded": sorted(_SECRET_NAMES | _SECRET_PARTS),
        "warnings": [
            "Adoption preserves raw imported persona files in a private snapshot.",
            "Imported memory remains unreviewed and is not added to shared memory.",
            "Canonical Persona v3 structuring is performed in Phase 3.",
        ],
    }


def adopt_runtime_instance(
    instance_id: str,
    *,
    persona_id: str | None = None,
    name: str | None = None,
    destination: str | Path | None = None,
    link_existing: bool = False,
    registry: RegistryService | None = None,
) -> AdoptionDraft:
    service = registry or RegistryService()
    preview = adoption_preview(
        instance_id,
        persona_id=persona_id,
        name=name,
        destination=destination,
        registry=service,
    )
    instance = service.get_runtime_instance(instance_id)
    assert instance is not None
    resolved_id = str(preview["persona_id"])
    resolved_name = str(preview["name"])
    project = Path(str(preview["destination"]))
    existing = service.get_persona(resolved_id)

    if existing and not link_existing:
        raise AdoptionError(
            f"persona ID already exists: {resolved_id}; use --link-existing only after reviewing the instance match"
        )
    if project.exists() and any(project.iterdir()) and not (existing and link_existing):
        raise AdoptionError(f"adoption destination is not empty: {project}")

    snapshot = snapshot_runtime_instance(instance, registry=service)
    warnings = list(preview["warnings"])

    if existing and link_existing:
        project = Path(existing.source_path).resolve() if existing.source_path else project
        if not (project / PROJECT_FILE).is_file():
            raise AdoptionError("existing persona has no usable source project")
        selected_skill = None
        imported_skills: tuple[str, ...] = ()
        memory_candidates = _write_memory_candidates(project, Path(instance.location), instance)
        warnings.append("Existing Persona was linked without replacing its source definition.")
    else:
        init_project(project, resolved_id, resolved_name)
        source = Path(instance.location).expanduser().resolve()
        soul_path = source / "SOUL.md"
        skills = _skill_directories(source)
        selected = _select_persona_skill(skills, resolved_id)
        imported_skills = _copy_imported_skills(project, source, selected)
        selected_skill = selected.name if selected else None
        _update_project_metadata(project, instance, resolved_id, resolved_name, soul_path, selected)
        memory_candidates = _write_memory_candidates(project, source, instance)

        private = project / ".private"
        adoption_metadata = {
            "format": "personadock-adoption",
            "format_version": 1,
            "created_at": _utc_now(),
            "instance": instance.to_dict(),
            "snapshot": snapshot.to_dict(),
            "selected_skill": selected_skill,
            "imported_skills": list(imported_skills),
            "memory_candidates": memory_candidates,
            "raw_source_preserved_at": snapshot.path,
        }
        (private / "adoption.json").write_text(
            json.dumps(adoption_metadata, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        errors = validate_project(project)
        if errors:
            raise AdoptionError("adopted project is invalid:\n- " + "\n- ".join(errors))
        service.register_persona(
            persona_id=resolved_id,
            name=resolved_name,
            version="0.1.0",
            source_path=project,
            schema_version=2,
            summary=f"从 {instance.adapter}/{instance.platform_instance_id} 接管的人格草稿。",
        )

    service.bind(resolved_id, instance.id, adopted=True)
    with service.database.session() as connection:
        connection.execute(
            "UPDATE snapshots SET persona_id = ? WHERE id = ?",
            (resolved_id, snapshot.id),
        )
    service.journal(
        "runtime-persona-adopted",
        persona_id=resolved_id,
        runtime_instance_id=instance.id,
        payload={
            "snapshot_id": snapshot.id,
            "destination": str(project),
            "link_existing": link_existing,
            "memory_candidates": memory_candidates,
        },
    )
    manifest = json.loads(Path(snapshot.manifest_path).read_text(encoding="utf-8"))
    return AdoptionDraft(
        persona_id=resolved_id,
        name=resolved_name,
        instance_id=instance.id,
        adapter=instance.adapter,
        destination=str(project),
        snapshot=snapshot,
        selected_skill=selected_skill,
        imported_skills=imported_skills,
        memory_candidates=memory_candidates,
        preserved_files=tuple(item["path"] for item in manifest["files"]),
        excluded_files=tuple(manifest["excluded"]),
        warnings=tuple(warnings),
    )
