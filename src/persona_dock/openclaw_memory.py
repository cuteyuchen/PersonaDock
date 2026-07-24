from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from persona_dock.adapters.openclaw import (
    OpenClawAdapter,
    OpenClawAdapterError,
)
from persona_dock.io import load_jsonl, load_yaml, write_jsonl
from persona_dock.project import PROJECT_FILE
from persona_dock.registry import RegistryService
from persona_dock.registry.database import registry_root


_MANAGED_START = "<!-- personadock-shared-memory:start -->"
_MANAGED_END = "<!-- personadock-shared-memory:end -->"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _workspace_path(adapter: OpenClawAdapter, workspace: str, relative: str) -> str:
    if adapter.runner.transport == "local":
        return str(Path(workspace).expanduser().resolve() / Path(relative))
    return str(PurePosixPath(workspace) / PurePosixPath(relative))


def _resolve_agent(adapter: OpenClawAdapter, agent_id: str):
    agent = adapter.agent(agent_id)
    if agent is None:
        raise OpenClawAdapterError(f"OpenClaw agent does not exist: {agent_id}")
    if not agent.workspace:
        raise OpenClawAdapterError(
            "OpenClaw did not report the Agent workspace; PersonaDock will not guess it"
        )
    return agent


def _candidate_signature(item: dict[str, Any]) -> tuple[str, str, str]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    return (
        str(source.get("agent") or ""),
        str(source.get("path") or ""),
        str(item.get("summary") or ""),
    )


def _strip_managed(text: str) -> str:
    return re.sub(
        re.escape(_MANAGED_START) + r".*?" + re.escape(_MANAGED_END),
        "",
        text,
        flags=re.DOTALL,
    ).strip()


def pull_openclaw_memory_candidates(
    persona_id: str,
    *,
    agent_id: str,
    container: str | None = None,
    ssh_host: str | None = None,
    adapter: OpenClawAdapter | None = None,
    registry: RegistryService | None = None,
) -> dict[str, Any]:
    adapter = adapter or OpenClawAdapter(container=container, ssh_host=ssh_host)
    service = registry or RegistryService()
    persona = service.get_persona(persona_id)
    if persona is None or not persona.source_path:
        raise OpenClawAdapterError(
            f"registered persona source is unavailable: {persona_id}"
        )
    agent = _resolve_agent(adapter, agent_id)
    sources: list[tuple[str, str]] = [("MEMORY.md", "long-term")]
    memory_dir = _workspace_path(adapter, agent.workspace, "memory")
    for path in adapter.runner.list_markdown(memory_dir):
        name = Path(path).name if adapter.runner.transport == "local" else PurePosixPath(path).name
        sources.append((f"memory/{name}", "daily-note"))

    candidates: list[dict[str, Any]] = []
    for relative, layer in sources:
        text = adapter.runner.read_text(
            _workspace_path(adapter, agent.workspace, relative)
        )
        summary = _strip_managed(text or "")
        if not summary:
            continue
        candidates.append(
            {
                "id": str(uuid.uuid4()),
                "type": "openclaw-memory-document",
                "layer": layer,
                "summary": summary[:4000],
                "source": {
                    "adapter": "openclaw",
                    "agent": agent_id,
                    "workspace": agent.workspace,
                    "path": relative,
                    "transport": adapter.runner.transport,
                    "container": container,
                    "ssh_host": ssh_host,
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
        "openclaw-memory-pulled",
        persona_id=persona_id,
        payload={
            "agent": agent_id,
            "workspace": agent.workspace,
            "transport": adapter.runner.transport,
            "candidates": len(candidates),
            "added": len(added),
            "output": str(output),
        },
    )
    return {
        "persona_id": persona_id,
        "agent": agent_id,
        "workspace": agent.workspace,
        "transport": adapter.runner.transport,
        "candidate_count": len(candidates),
        "added": len(added),
        "output": str(output),
    }


def _render_reviewed_memory(project: Path) -> str:
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
    bullets = "\n".join(f"- {entry}" for entry in entries)
    return (
        f"{_MANAGED_START}\n"
        "## PersonaDock reviewed shared memory\n\n"
        f"{bullets}\n"
        f"{_MANAGED_END}"
    )


def _replace_managed(existing: str, managed: str) -> str:
    pattern = re.compile(
        re.escape(_MANAGED_START) + r".*?" + re.escape(_MANAGED_END),
        re.DOTALL,
    )
    clean = pattern.sub("", existing).strip()
    if not managed:
        return clean + ("\n" if clean else "")
    return (clean + "\n\n" if clean else "") + managed + "\n"


def _record_snapshot(
    service: RegistryService,
    *,
    persona_id: str,
    agent_id: str,
    workspace: str,
    transport: str,
    path: Path,
) -> None:
    instance_id = None
    for instance in service.list_runtime_instances(adapter="openclaw"):
        if (
            instance.transport == transport
            and instance.platform_instance_id == agent_id
            and instance.location == workspace
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
                        "agent": agent_id,
                        "workspace": workspace,
                        "transport": transport,
                        "file": "MEMORY.md",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                _utc_now(),
            ),
        )


def push_openclaw_shared_memory(
    persona_id: str,
    *,
    agent_id: str,
    container: str | None = None,
    ssh_host: str | None = None,
    adapter: OpenClawAdapter | None = None,
    registry: RegistryService | None = None,
) -> dict[str, Any]:
    adapter = adapter or OpenClawAdapter(container=container, ssh_host=ssh_host)
    service = registry or RegistryService()
    persona = service.get_persona(persona_id)
    if persona is None or not persona.source_path:
        raise OpenClawAdapterError(
            f"registered persona source is unavailable: {persona_id}"
        )
    project = Path(persona.source_path)
    if not (project / PROJECT_FILE).is_file():
        raise OpenClawAdapterError(
            f"persona project is missing {PROJECT_FILE}: {project}"
        )
    agent = _resolve_agent(adapter, agent_id)
    destination = _workspace_path(adapter, agent.workspace, "MEMORY.md")
    existing = adapter.runner.read_text(destination) or ""
    managed = _render_reviewed_memory(project)
    updated = _replace_managed(existing, managed)

    backup = (
        registry_root()
        / "snapshots"
        / "openclaw"
        / agent_id
        / f"{_timestamp()}-{uuid.uuid4().hex[:8]}-MEMORY.md"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(existing, encoding="utf-8")
    _record_snapshot(
        service,
        persona_id=persona_id,
        agent_id=agent_id,
        workspace=agent.workspace,
        transport=adapter.runner.transport,
        path=backup,
    )

    adapter.runner.write_text(destination, updated)
    verification = adapter.runner.read_text(destination)
    if verification != updated:
        adapter.runner.write_text(destination, existing)
        raise OpenClawAdapterError(
            "OpenClaw MEMORY.md verification failed; the original content was restored"
        )
    index_result = adapter.runner.run(
        ["memory", "index", "--agent", agent_id, "--force"],
        timeout=300,
    )
    if not index_result.ok:
        adapter.runner.write_text(destination, existing)
        adapter.runner.run(
            ["memory", "index", "--agent", agent_id, "--force"],
            timeout=300,
        )
        detail = index_result.stderr.strip() or index_result.stdout.strip() or "memory index failed"
        raise OpenClawAdapterError(
            f"OpenClaw memory indexing failed; MEMORY.md was restored: {detail}"
        )

    service.journal(
        "openclaw-memory-pushed",
        persona_id=persona_id,
        payload={
            "agent": agent_id,
            "workspace": agent.workspace,
            "transport": adapter.runner.transport,
            "backup": str(backup),
            "managed_chars": len(managed),
            "index_command": list(index_result.command),
        },
    )
    return {
        "persona_id": persona_id,
        "agent": agent_id,
        "workspace": agent.workspace,
        "transport": adapter.runner.transport,
        "backup": str(backup),
        "managed_chars": len(managed),
        "destination": destination,
        "indexed": True,
    }
