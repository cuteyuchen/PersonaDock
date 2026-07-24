from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from persona_dock.registry.models import DiscoveryReport, RuntimeInstanceRecord
from persona_dock.registry.service import RegistryService


@dataclass(frozen=True)
class DiscoveredInstance:
    adapter: str
    transport: str
    platform_instance_id: str
    display_name: str
    location: str
    capabilities: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_registry(self) -> dict[str, Any]:
        return asdict(self)


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=12,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def _read_heading(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            value = line.strip()
            if value.startswith("#"):
                heading = value.lstrip("#").strip()
                return heading or None
    except OSError:
        return None
    return None


def _workspace_metadata(path: Path) -> dict[str, Any]:
    files = [
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "TOOLS.md",
        "MEMORY.md",
    ]
    present = [name for name in files if (path / name).is_file()]
    skills = path / "skills"
    skill_count = 0
    if skills.is_dir():
        try:
            skill_count = sum(1 for child in skills.iterdir() if child.is_dir())
        except OSError:
            skill_count = 0
    return {
        "exists": path.exists(),
        "files": present,
        "skill_count": skill_count,
        "has_memory_directory": (path / "memory").is_dir(),
        "identity_heading": _read_heading(path / "IDENTITY.md"),
        "soul_heading": _read_heading(path / "SOUL.md"),
    }


def _hermes_metadata(path: Path) -> dict[str, Any]:
    markers = [
        "SOUL.md",
        "config.yaml",
        ".env",
        "skills",
        "memories",
        "sessions",
        "profiles",
    ]
    present = [name for name in markers if (path / name).exists()]
    skills = path / "skills"
    skill_count = 0
    if skills.is_dir():
        try:
            skill_count = sum(1 for child in skills.iterdir() if child.is_dir())
        except OSError:
            pass
    return {
        "exists": path.exists(),
        "markers": present,
        "skill_count": skill_count,
        "soul_heading": _read_heading(path / "SOUL.md"),
        "has_memory": (path / "memories").exists(),
        "has_sessions": (path / "sessions").exists(),
    }


def _parse_key_value_output(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([^:]+):\s*(.*?)\s*$", line)
        if match:
            values[match.group(1).strip().lower().replace(" ", "_")] = match.group(2).strip()
    return values


def _parse_hermes_profile_names(text: str) -> list[tuple[str, bool]]:
    names: list[tuple[str, bool]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or set(line) <= {"-", "=", "+", "|", " "}:
            continue
        lowered = line.lower()
        if lowered.startswith(("profile", "name ", "profiles")):
            continue
        active = line.startswith("*")
        line = line.lstrip("* ")
        if "|" in line:
            values = [value.strip() for value in line.split("|") if value.strip()]
            candidate = values[0] if values else ""
        else:
            candidate = line.split()[0] if line.split() else ""
        if not candidate or candidate.lower() in {"name", "profile"}:
            continue
        if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", candidate):
            names.append((candidate, active))
    unique: dict[str, bool] = {}
    for name, active in names:
        unique[name] = unique.get(name, False) or active
    return sorted(unique.items(), key=lambda item: (item[0] != "default", item[0].lower()))


def _hermes_roots() -> list[Path]:
    values: list[Path] = []
    if os.environ.get("HERMES_HOME"):
        values.append(Path(os.path.expandvars(os.path.expanduser(os.environ["HERMES_HOME"]))))
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        values.append(Path(os.environ["LOCALAPPDATA"]) / "hermes")
    values.append(Path.home() / ".hermes")
    unique: dict[str, Path] = {}
    for value in values:
        path = value.expanduser().resolve()
        unique[os.path.normcase(str(path))] = path
    return list(unique.values())


def discover_hermes() -> tuple[list[DiscoveredInstance], list[str]]:
    executable = shutil.which("hermes")
    warnings: list[str] = []
    values: list[DiscoveredInstance] = []

    if executable:
        result = _run([executable, "profile", "list"])
        if result and result.returncode == 0:
            for name, active in _parse_hermes_profile_names(result.stdout):
                details_result = _run([executable, "profile", "show", name])
                details = _parse_key_value_output(details_result.stdout) if details_result and details_result.returncode == 0 else {}
                raw_path = details.get("path") or details.get("home") or details.get("home_directory")
                if raw_path:
                    path = Path(os.path.expandvars(os.path.expanduser(raw_path))).resolve()
                else:
                    root = _hermes_roots()[0]
                    path = root if name == "default" else root / "profiles" / name
                metadata = _hermes_metadata(path)
                metadata.update(
                    {
                        "active": active,
                        "discovery_source": "hermes-cli",
                        "profile_details": details,
                    }
                )
                values.append(
                    DiscoveredInstance(
                        adapter="hermes",
                        transport="local",
                        platform_instance_id=name,
                        display_name=metadata.get("soul_heading") or name,
                        location=str(path),
                        capabilities={
                            "native_profile": True,
                            "read_only_discovery": True,
                            "memory_pull": False,
                            "session_summary_pull": False,
                        },
                        metadata=metadata,
                    )
                )
        elif result:
            warnings.append(
                "Hermes CLI was found but `hermes profile list` failed: "
                + (result.stderr.strip() or result.stdout.strip() or str(result.returncode))
            )

    if not values:
        for root in _hermes_roots():
            root_metadata = _hermes_metadata(root)
            if root_metadata["markers"]:
                root_metadata.update({"active": None, "discovery_source": "filesystem-read-only"})
                values.append(
                    DiscoveredInstance(
                        adapter="hermes",
                        transport="local",
                        platform_instance_id="default",
                        display_name=root_metadata.get("soul_heading") or "default",
                        location=str(root),
                        capabilities={
                            "native_profile": False,
                            "read_only_discovery": True,
                            "memory_pull": False,
                            "session_summary_pull": False,
                        },
                        metadata=root_metadata,
                    )
                )
            profiles = root / "profiles"
            if profiles.is_dir():
                try:
                    children = sorted(child for child in profiles.iterdir() if child.is_dir())
                except OSError:
                    children = []
                for child in children:
                    metadata = _hermes_metadata(child)
                    if not metadata["markers"]:
                        continue
                    metadata.update({"active": None, "discovery_source": "filesystem-read-only"})
                    values.append(
                        DiscoveredInstance(
                            adapter="hermes",
                            transport="local",
                            platform_instance_id=child.name,
                            display_name=metadata.get("soul_heading") or child.name,
                            location=str(child.resolve()),
                            capabilities={
                                "native_profile": False,
                                "read_only_discovery": True,
                                "memory_pull": False,
                                "session_summary_pull": False,
                            },
                            metadata=metadata,
                        )
                    )

    return _deduplicate(values), warnings


def _openclaw_agents_from_json(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("agents", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if any(key in payload for key in ("id", "agentId", "workspace")):
            return [payload]
    return []


def _agent_value(agent: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = agent.get(key)
        if value is not None:
            return value
    return None


def _openclaw_default_workspace() -> Path:
    if os.environ.get("OPENCLAW_WORKSPACE_DIR"):
        return Path(os.path.expandvars(os.path.expanduser(os.environ["OPENCLAW_WORKSPACE_DIR"]))).resolve()
    state = Path(os.path.expandvars(os.path.expanduser(os.environ.get("OPENCLAW_STATE_DIR", "~/.openclaw")))).resolve()
    return state / "workspace"


def discover_openclaw() -> tuple[list[DiscoveredInstance], list[str]]:
    executable = shutil.which("openclaw")
    warnings: list[str] = []
    values: list[DiscoveredInstance] = []

    if executable:
        result = _run([executable, "agents", "list", "--json"])
        if result and result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as error:
                warnings.append(f"OpenClaw returned invalid JSON: {error}")
            else:
                for agent in _openclaw_agents_from_json(payload):
                    agent_id = str(_agent_value(agent, "id", "agentId", "agent_id", "name") or "main")
                    raw_workspace = _agent_value(agent, "workspace", "workspacePath", "workspace_path")
                    if raw_workspace:
                        workspace = Path(os.path.expandvars(os.path.expanduser(str(raw_workspace)))).resolve()
                    else:
                        state = Path(os.path.expandvars(os.path.expanduser(os.environ.get("OPENCLAW_STATE_DIR", "~/.openclaw")))).resolve()
                        workspace = _openclaw_default_workspace() if agent_id == "main" else state / f"workspace-{agent_id}"
                    identity = agent.get("identity") if isinstance(agent.get("identity"), dict) else {}
                    metadata = _workspace_metadata(workspace)
                    metadata.update(
                        {
                            "discovery_source": "openclaw-cli-json",
                            "identity": identity,
                            "agent": agent,
                        }
                    )
                    display_name = str(identity.get("name") or metadata.get("identity_heading") or agent.get("name") or agent_id)
                    values.append(
                        DiscoveredInstance(
                            adapter="openclaw",
                            transport="local",
                            platform_instance_id=agent_id,
                            display_name=display_name,
                            location=str(workspace),
                            capabilities={
                                "native_agent": True,
                                "read_only_discovery": True,
                                "memory_pull": False,
                                "session_summary_pull": False,
                            },
                            metadata=metadata,
                        )
                    )
        elif result:
            warnings.append(
                "OpenClaw CLI was found but `openclaw agents list --json` failed: "
                + (result.stderr.strip() or result.stdout.strip() or str(result.returncode))
            )

    if not values:
        workspace = _openclaw_default_workspace()
        metadata = _workspace_metadata(workspace)
        if metadata["files"] or metadata["has_memory_directory"] or metadata["skill_count"]:
            metadata.update({"discovery_source": "filesystem-read-only"})
            values.append(
                DiscoveredInstance(
                    adapter="openclaw",
                    transport="local",
                    platform_instance_id="main",
                    display_name=metadata.get("identity_heading") or metadata.get("soul_heading") or "main",
                    location=str(workspace),
                    capabilities={
                        "native_agent": False,
                        "read_only_discovery": True,
                        "memory_pull": False,
                        "session_summary_pull": False,
                    },
                    metadata=metadata,
                )
            )

    return _deduplicate(values), warnings


def _deduplicate(values: Iterable[DiscoveredInstance]) -> list[DiscoveredInstance]:
    unique: dict[tuple[str, str, str, str], DiscoveredInstance] = {}
    for value in values:
        key = (
            value.adapter,
            value.transport,
            value.platform_instance_id,
            os.path.normcase(value.location),
        )
        unique[key] = value
    return sorted(
        unique.values(),
        key=lambda item: (item.adapter, item.display_name.lower(), item.platform_instance_id),
    )


def discover_runtime_instances(
    target: str | None = None,
    *,
    registry: RegistryService | None = None,
) -> DiscoveryReport:
    if target not in {None, "hermes", "openclaw"}:
        raise ValueError(f"unsupported discovery target: {target}")
    registry = registry or RegistryService()
    discovered: list[DiscoveredInstance] = []
    warnings: list[str] = []
    scanned: list[str] = []

    if target in {None, "hermes"}:
        values, adapter_warnings = discover_hermes()
        discovered.extend(values)
        warnings.extend(adapter_warnings)
        scanned.append("hermes")
    if target in {None, "openclaw"}:
        values, adapter_warnings = discover_openclaw()
        discovered.extend(values)
        warnings.extend(adapter_warnings)
        scanned.append("openclaw")

    records: list[RuntimeInstanceRecord] = []
    for value in _deduplicate(discovered):
        record = registry.upsert_runtime_instance(**value.to_registry())
        records.append(record)
        registry.journal(
            "runtime-instance-discovered",
            runtime_instance_id=record.id,
            payload={
                "adapter": record.adapter,
                "transport": record.transport,
                "platform_instance_id": record.platform_instance_id,
                "location": record.location,
                "source": record.metadata.get("discovery_source"),
            },
        )

    return DiscoveryReport(
        scanned_adapters=tuple(scanned),
        instances=tuple(records),
        warnings=tuple(warnings),
        metadata={"read_only": True},
    )
