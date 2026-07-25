from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from persona_dock.adapters.hermes import HermesAdapter, HermesAdapterError
from persona_dock.adapters.openclaw import OpenClawAdapter, OpenClawAdapterError
from persona_dock.registry.models import RuntimeInstanceRecord


class SessionSourceError(RuntimeError):
    """Raised when a runtime session cannot be exported without touching its state."""


@dataclass(frozen=True)
class ExportedSession:
    adapter: str
    runtime_instance_id: str
    source_session_id: str
    path: str
    command: tuple[str, ...]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return clean[:80] or "session"


def _find_export(root: Path) -> Path:
    if root.is_file():
        return root
    candidates = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".jsonl", ".json"}
        ),
        key=lambda path: (path.suffix.lower() != ".jsonl", len(path.parts), str(path)),
    )
    if not candidates:
        raise SessionSourceError(f"native session export produced no JSON/JSONL file under {root}")
    return candidates[0]


def export_hermes_session(
    instance: RuntimeInstanceRecord,
    session_id: str,
    destination_root: Path,
) -> ExportedSession:
    container = str(instance.metadata.get("container") or "") or None
    adapter = HermesAdapter(container=container)
    destination_root.mkdir(parents=True, exist_ok=True)
    local = destination_root / f"hermes-{_safe_name(session_id)}.jsonl"
    if container:
        remote = f"/tmp/personadock-{uuid.uuid4().hex}.jsonl"
        result = adapter.runner.run(
            ["sessions", "export", remote, "--session-id", session_id],
            timeout=120,
            check=True,
        )
        try:
            adapter.runner.docker_copy_from(remote, local)
        finally:
            adapter.runner.run(["shell", "rm", "-f", remote], timeout=15)
    else:
        result = adapter.runner.run(
            ["sessions", "export", str(local), "--session-id", session_id],
            timeout=120,
            check=True,
        )
    if not local.is_file():
        raise SessionSourceError("Hermes reported success but did not create the session export")
    return ExportedSession(
        adapter="hermes",
        runtime_instance_id=instance.id,
        source_session_id=session_id,
        path=str(local),
        command=result.command,
        metadata={
            "profile": instance.platform_instance_id,
            "transport": instance.transport,
            "container": container,
            "native_command": "hermes sessions export",
        },
    )


def export_openclaw_session(
    instance: RuntimeInstanceRecord,
    session_key: str,
    destination_root: Path,
) -> ExportedSession:
    container = str(instance.metadata.get("container") or "") or None
    ssh_host = str(instance.metadata.get("ssh_host") or "") or None
    adapter = OpenClawAdapter(container=container, ssh_host=ssh_host)
    destination_root.mkdir(parents=True, exist_ok=True)
    local_root = destination_root / f"openclaw-{_safe_name(session_key)}"
    if adapter.runner.transport == "local":
        output = str(local_root)
        result = adapter.runner.run(
            [
                "sessions",
                "export-trajectory",
                "--session-key",
                session_key,
                "--output",
                output,
                "--json",
            ],
            timeout=120,
            check=True,
        )
    else:
        remote = f"/tmp/personadock-session-{uuid.uuid4().hex}"
        result = adapter.runner.run(
            [
                "sessions",
                "export-trajectory",
                "--session-key",
                session_key,
                "--output",
                remote,
                "--json",
            ],
            timeout=120,
            check=True,
        )
        try:
            adapter.runner.copy_from(remote, local_root)
        finally:
            adapter.runner.shell(f"rm -rf {remote!r}", timeout=20)
    if not local_root.exists() and result.stdout.strip():
        try:
            json.loads(result.stdout)
            local_root.with_suffix(".json").write_text(result.stdout, encoding="utf-8")
            local_root = local_root.with_suffix(".json")
        except json.JSONDecodeError:
            pass
    export_file = _find_export(local_root)
    return ExportedSession(
        adapter="openclaw",
        runtime_instance_id=instance.id,
        source_session_id=session_key,
        path=str(export_file),
        command=result.command,
        metadata={
            "agent": instance.platform_instance_id,
            "transport": instance.transport,
            "container": container,
            "ssh_host": ssh_host,
            "native_command": "openclaw sessions export-trajectory",
        },
    )


def export_runtime_session(
    instance: RuntimeInstanceRecord,
    session_identifier: str,
    destination_root: Path,
) -> ExportedSession:
    if not session_identifier.strip():
        raise SessionSourceError("a session ID/key is required")
    try:
        if instance.adapter == "hermes":
            return export_hermes_session(instance, session_identifier, destination_root)
        if instance.adapter == "openclaw":
            return export_openclaw_session(instance, session_identifier, destination_root)
    except (HermesAdapterError, OpenClawAdapterError) as error:
        raise SessionSourceError(str(error)) from error
    raise SessionSourceError(f"session export is unsupported for adapter: {instance.adapter}")
