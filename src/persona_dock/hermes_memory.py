from __future__ import annotations

import json
import re
import shlex
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from persona_dock.adapters.hermes import HermesAdapter, HermesAdapterError
from persona_dock.io import load_jsonl, load_yaml, write_jsonl
from persona_dock.project import PROJECT_FILE
from persona_dock.registry import RegistryService
from persona_dock.registry.database import registry_root


_MEMORY_FILES = ("memories/MEMORY.md", "memories/USER.md")
_MANAGED_START = "<!-- personadock-shared-memory:start -->"
_MANAGED_END = "<!-- personadock-shared-memory:end -->"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _profile_root(adapter: HermesAdapter, profile: str) -> str:
    value = adapter.profile(profile)
    if value is None:
        raise HermesAdapterError(f"Hermes profile does not exist: {profile}")
    if not value.path:
        raise HermesAdapterError(
            "Hermes did not report the profile path; PersonaDock will not guess it"
        )
    return value.path


def _run_host(command: list[str], *, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
        raise HermesAdapterError(f"failed to run {' '.join(command)}: {error}") from error


def _read_profile_file(
    adapter: HermesAdapter,
    profile_root: str,
    relative: str,
) -> str:
    if not adapter.container:
        path = Path(profile_root).expanduser().resolve() / Path(relative)
        return (
            path.read_text(encoding="utf-8", errors="replace")
            if path.is_file()
            else ""
        )

    remote = str(PurePosixPath(profile_root) / PurePosixPath(relative))
    exists = _run_host(
        [
            adapter.runner.docker_executable,
            "exec",
            adapter.container,
            "sh",
            "-lc",
            f"test -f {shlex.quote(remote)}",
        ]
    )
    if exists.returncode != 0:
        return ""
    with tempfile.TemporaryDirectory(prefix="personadock-hermes-memory-") as directory:
        local = Path(directory) / Path(relative).name
        adapter.runner.docker_copy_from(remote, local)
        return local.read_text(encoding="utf-8", errors="replace")


def _write_profile_file(
    adapter: HermesAdapter,
    profile_root: str,
    relative: str,
    content: str,
) -> None:
    if not adapter.container:
        path = Path(profile_root).expanduser().resolve() / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return

    remote = str(PurePosixPath(profile_root) / PurePosixPath(relative))
    parent = str(PurePosixPath(remote).parent)
    mkdir = _run_host(
        [
            adapter.runner.docker_executable,
            "exec",
            adapter.container,
            "sh",
            "-lc",
            f"mkdir -p {shlex.quote(parent)}",
        ]
    )
    if mkdir.returncode != 0:
        raise HermesAdapterError(
            mkdir.stderr.strip() or mkdir.stdout.strip() or "failed to create memory directory"
        )
    with tempfile.TemporaryDirectory(prefix="personadock-hermes-memory-") as directory:
        local = Path(directory) / Path(relative).name
        local.write_text(content, encoding="utf-8")
        adapter.runner.docker_copy_to(local, remote)


def _candidate_signature(item: dict[str, Any]) -> tuple[str, str, str]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    return (
        str(source.get("profile") or ""),
        str(source.get("path") or ""),
        str(item.get("summary") or ""),
    )


def pull_hermes_memory_candidates(
    persona_id: str,
    *,
    profile: str,
    container: str | None = None,
    adapter: HermesAdapter | None = None,
    registry: RegistryService | None = None,
) -> dict[str, Any]:
    adapter = adapter or HermesAdapter(container=container)
    service = registry or RegistryService()
    persona = service.get_persona(persona_id)
    if persona is None or not persona.source_path:
        raise HermesAdapterError(
            f"registered persona source is unavailable: {persona_id}"
        )
    profile_root = _profile_root(adapter, profile)
    candidates: list[dict[str, Any]] = []
    for relative in _MEMORY_FILES:
        text = _read_profile_file(adapter, profile_root, relative).strip()
        if not text:
            continue
        text = re.sub(
            re.escape(_MANAGED_START)
            + r".*?"
            + re.escape(_MANAGED_END),
            "",
            text,
            flags=re.DOTALL,
        ).strip()
        target = "user" if relative.endswith("USER.md") else "memory"
        for entry in re.split(r"\n\s*§\s*\n", text):
            summary = entry.strip()
            if not summary:
                continue
            candidates.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": "hermes-memory",
                    "target": target,
                    "summary": summary[:1000],
                    "source": {
                        "adapter": "hermes",
                        "profile": profile,
                        "container": container,
                        "path": relative,
                    },
                    "reviewed": False,
                    "sensitivity": "private",
                    "sync_scope": "local-only",
                    "status": "pending",
                    "created_at": _utc_now(),
                }
            )

    output = Path(persona.source_path) / ".private" / "memory-candidates.jsonl"
    existing = load_jsonl(output)
    signatures = {_candidate_signature(item) for item in existing}
    added = [
        item
        for item in candidates
        if _candidate_signature(item) not in signatures
    ]
    write_jsonl(output, [*existing, *added])
    service.journal(
        "hermes-memory-pulled",
        persona_id=persona_id,
        payload={
            "profile": profile,
            "container": container,
            "candidates": len(candidates),
            "added": len(added),
            "output": str(output),
        },
    )
    return {
        "persona_id": persona_id,
        "profile": profile,
        "container": container,
        "candidate_count": len(candidates),
        "added": len(added),
        "output": str(output),
    }


def _render_reviewed_shared_memory(project: Path) -> str:
    records = [
        item
        for item in load_jsonl(project / "memory" / "seed.jsonl")
        if item.get("reviewed") is True
    ]
    profile = load_yaml(project / "memory" / "profile.yaml")
    entries: list[str] = []
    for key in ("user_preferences", "relationship_facts", "notes"):
        values = profile.get(key, [])
        if isinstance(values, list):
            entries.extend(str(item).strip() for item in values if str(item).strip())
    for item in records:
        summary = str(item.get("summary") or item.get("text") or "").strip()
        if summary:
            entries.append(summary)
    if not entries:
        return ""
    return (
        _MANAGED_START
        + "\n"
        + "\n§\n".join(entries)
        + "\n"
        + _MANAGED_END
    )


def _replace_managed_section(existing: str, managed: str) -> str:
    pattern = re.compile(
        re.escape(_MANAGED_START)
        + r".*?"
        + re.escape(_MANAGED_END),
        re.DOTALL,
    )
    clean = pattern.sub("", existing).strip()
    if not managed:
        return clean + ("\n" if clean else "")
    return (clean + "\n§\n" if clean else "") + managed + "\n"


def _record_memory_snapshot(
    service: RegistryService,
    *,
    persona_id: str,
    profile: str,
    container: str | None,
    path: Path,
) -> None:
    transport = "docker" if container else "local"
    instance_id = None
    for instance in service.list_runtime_instances(adapter="hermes"):
        if (
            instance.transport == transport
            and instance.platform_instance_id == profile
        ):
            instance_id = instance.id
            break
    with service.database.session() as connection:
        connection.execute(
            """
            INSERT INTO snapshots(
                id, persona_id, runtime_instance_id, kind, path, metadata_json, created_at
            ) VALUES(?, ?, ?, 'pre-memory-push', ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                persona_id,
                instance_id,
                str(path),
                json.dumps(
                    {
                        "profile": profile,
                        "container": container,
                        "file": "memories/MEMORY.md",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                _utc_now(),
            ),
        )


def push_hermes_shared_memory(
    persona_id: str,
    *,
    profile: str,
    container: str | None = None,
    adapter: HermesAdapter | None = None,
    registry: RegistryService | None = None,
) -> dict[str, Any]:
    adapter = adapter or HermesAdapter(container=container)
    service = registry or RegistryService()
    persona = service.get_persona(persona_id)
    if persona is None or not persona.source_path:
        raise HermesAdapterError(
            f"registered persona source is unavailable: {persona_id}"
        )
    project = Path(persona.source_path)
    if not (project / PROJECT_FILE).is_file():
        raise HermesAdapterError(
            f"persona project is missing {PROJECT_FILE}: {project}"
        )

    managed = _render_reviewed_shared_memory(project)
    profile_root = _profile_root(adapter, profile)
    relative = "memories/MEMORY.md"
    existing = _read_profile_file(adapter, profile_root, relative)
    backup = (
        registry_root()
        / "snapshots"
        / "hermes"
        / profile
        / f"{_timestamp()}-{uuid.uuid4().hex[:8]}-memory.md"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(existing, encoding="utf-8")
    _record_memory_snapshot(
        service,
        persona_id=persona_id,
        profile=profile,
        container=container,
        path=backup,
    )

    updated = _replace_managed_section(existing, managed)
    _write_profile_file(adapter, profile_root, relative, updated)
    verification = _read_profile_file(adapter, profile_root, relative)
    if verification != updated:
        _write_profile_file(adapter, profile_root, relative, existing)
        raise HermesAdapterError(
            "Hermes memory verification failed; the original file was restored"
        )

    service.journal(
        "hermes-memory-pushed",
        persona_id=persona_id,
        payload={
            "profile": profile,
            "container": container,
            "backup": str(backup),
            "managed_chars": len(managed),
        },
    )
    return {
        "persona_id": persona_id,
        "profile": profile,
        "container": container,
        "backup": str(backup),
        "managed_chars": len(managed),
        "destination": f"{profile_root}/{relative}",
    }
