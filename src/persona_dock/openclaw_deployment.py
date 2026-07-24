from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from persona_dock.adapters.openclaw import (
    OpenClawAdapter,
    OpenClawAdapterError,
    OpenClawAgent,
    validate_agent_id,
)
from persona_dock.io import sha256_file
from persona_dock.packaging import inspect_package
from persona_dock.registry import RegistryService
from persona_dock.registry.database import registry_root


@dataclass(frozen=True)
class OpenClawOverlayArtifact:
    path: str
    persona_id: str
    version: str
    agent: str
    skill_id: str
    package: str
    package_sha256: str
    owned_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpenClawDeploymentPlan:
    id: str
    package: str
    persona_id: str
    persona_version: str
    agent: str
    agent_explicit: bool
    existing_agent: bool
    workspace: str
    state_directory: str | None
    container: str | None
    ssh_host: str | None
    model: str | None
    bindings: tuple[str, ...]
    take_ownership: bool
    artifact: OpenClawOverlayArtifact
    snapshot_path: str | None
    conflicts: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    preserves: tuple[str, ...]
    warnings: tuple[str, ...]
    requires_confirmation: bool = True

    @property
    def transport(self) -> str:
        if self.container:
            return "docker"
        if self.ssh_host:
            return "ssh"
        return "local"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["transport"] = self.transport
        value["artifact"] = self.artifact.to_dict()
        value["commands"] = [list(command) for command in self.commands]
        return value


@dataclass(frozen=True)
class OpenClawDeploymentResult:
    deployment_id: str
    persona_id: str
    persona_version: str
    agent: str
    workspace: str
    state_directory: str | None
    transport: str
    container: str | None
    ssh_host: str | None
    snapshot_path: str | None
    created_agent: bool
    verification: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_skill_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "persona"


def _workspace_path(adapter: OpenClawAdapter, workspace: str, relative: str) -> str:
    if adapter.runner.transport == "local":
        return str(Path(workspace).expanduser().resolve() / Path(relative))
    return str(PurePosixPath(workspace) / PurePosixPath(relative))


def _absolute_workspace(adapter: OpenClawAdapter, workspace: str) -> str:
    if adapter.runner.transport == "local":
        path = Path(workspace).expanduser().resolve()
        if not path.is_absolute():
            raise OpenClawAdapterError("OpenClaw workspace must be absolute")
        return str(path)
    path = PurePosixPath(workspace)
    if not path.is_absolute():
        raise OpenClawAdapterError(
            "Docker and SSH OpenClaw workspaces must be explicit absolute POSIX paths"
        )
    return str(path)


def _source_project(archive: zipfile.ZipFile) -> dict[str, Any]:
    if "source/companion.yaml" not in archive.namelist():
        return {}
    value = yaml.safe_load(archive.read("source/companion.yaml").decode("utf-8"))
    return value if isinstance(value, dict) else {}


def _identity_markdown(project: dict[str, Any], *, name: str, summary: str) -> str:
    voice = project.get("voice") if isinstance(project.get("voice"), dict) else {}
    theme = str(voice.get("style") or summary or "由 PersonaDock 管理的 AI 人格").strip()
    return (
        "# IDENTITY.md - Who Am I?\n\n"
        f"- Name: {name}\n"
        f"- Theme: {theme}\n"
        "\n"
        "This identity is managed from a Canonical Persona by PersonaDock.\n"
    )


def build_openclaw_overlay(
    package: str | Path,
    *,
    agent: str | None = None,
    output: Path | None = None,
) -> OpenClawOverlayArtifact:
    package_path = Path(package).expanduser().resolve()
    info = inspect_package(package_path)
    if info.get("integrity") != "ok":
        raise OpenClawAdapterError("PersonaPack integrity check failed")
    if "openclaw" not in info.get("targets", {}):
        raise OpenClawAdapterError("PersonaPack does not contain an OpenClaw target")

    persona_id = str(info.get("id") or "persona")
    version = str(info.get("version") or "0.0.0")
    resolved_agent = agent or persona_id
    validate_agent_id(
        resolved_agent,
        explicit_main=agent is not None and resolved_agent == "main",
    )
    destination = (
        output.expanduser().resolve()
        if output
        else registry_root()
        / "artifacts"
        / "openclaw"
        / persona_id
        / version
        / resolved_agent
    )
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    prefix = "targets/openclaw/"
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if prefix + "SOUL.md" not in names:
            raise OpenClawAdapterError("OpenClaw target is missing SOUL.md")
        project = _source_project(archive)
        name = str(project.get("name") or info.get("name") or resolved_agent)
        summary = str(project.get("summary") or info.get("summary") or "")
        (destination / "SOUL.md").write_bytes(archive.read(prefix + "SOUL.md"))
        (destination / "IDENTITY.md").write_text(
            _identity_markdown(project, name=name, summary=summary),
            encoding="utf-8",
        )

        skill_members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and member.filename.startswith(prefix + "skills/")
        ]
        skill_roots = sorted(
            {
                member.filename[len(prefix + "skills/") :].split("/", 1)[0]
                for member in skill_members
                if "/" in member.filename[len(prefix + "skills/") :]
            }
        )
        skill_id = _safe_skill_id(skill_roots[0] if skill_roots else f"{persona_id}-persona")
        for member in skill_members:
            relative = member.filename[len(prefix + "skills/") :]
            parts = PurePosixPath(relative).parts
            if not parts or parts[0] not in skill_roots:
                continue
            target_relative = Path("skills") / skill_id / Path(*parts[1:])
            if target_relative.is_absolute() or ".." in target_relative.parts:
                raise OpenClawAdapterError(f"unsafe PersonaPack path: {member.filename}")
            target = destination / target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))

    owned_paths = ["SOUL.md", "IDENTITY.md", f"skills/{skill_id}", "personadock-manifest.json"]
    files = {
        path.relative_to(destination).as_posix(): sha256_file(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    manifest = {
        "format": "personadock-openclaw-workspace-overlay",
        "format_version": 2,
        "persona_id": persona_id,
        "persona_version": version,
        "target_agent": resolved_agent,
        "generated_at": _utc_now(),
        "owned_paths": owned_paths,
        "files": files,
        "preserve": [
            "AGENTS.md",
            "USER.md",
            "TOOLS.md",
            "HEARTBEAT.md",
            "BOOTSTRAP.md",
            "MEMORY.md",
            "memory/",
            "DREAMS.md",
            "workspace-local skills outside the PersonaDock skill directory",
            "agentDir, auth profiles, sessions, transcripts, and indexes outside the workspace",
        ],
        "privacy": {
            "credentials_included": False,
            "sessions_included": False,
            "memory_included": False,
            "raw_chat_included": False,
        },
    }
    manifest_path = destination / "personadock-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    files["personadock-manifest.json"] = sha256_file(manifest_path)
    return OpenClawOverlayArtifact(
        path=str(destination),
        persona_id=persona_id,
        version=version,
        agent=resolved_agent,
        skill_id=skill_id,
        package=str(package_path),
        package_sha256=str(info.get("package_sha256") or sha256_file(package_path)),
        owned_paths=tuple(owned_paths),
    )


def _load_workspace_manifest(
    adapter: OpenClawAdapter,
    workspace: str,
) -> dict[str, Any] | None:
    text = adapter.runner.read_text(
        _workspace_path(adapter, workspace, "personadock-manifest.json")
    )
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise OpenClawAdapterError(
            f"existing personadock-manifest.json is invalid: {error}"
        ) from error
    if not isinstance(value, dict) or value.get("format") != "personadock-openclaw-workspace-overlay":
        raise OpenClawAdapterError(
            "existing personadock-manifest.json is not a PersonaDock OpenClaw ownership manifest"
        )
    return value


def _ownership_conflicts(
    adapter: OpenClawAdapter,
    workspace: str,
    artifact: OpenClawOverlayArtifact,
    existing_manifest: dict[str, Any] | None,
) -> list[str]:
    if existing_manifest:
        return []
    values: list[str] = []
    for relative in ("SOUL.md", "IDENTITY.md", f"skills/{artifact.skill_id}"):
        if adapter.runner.exists(_workspace_path(adapter, workspace, relative)):
            values.append(relative)
    return values


def plan_openclaw_deployment(
    package: str | Path,
    *,
    agent: str | None = None,
    agent_explicit: bool = False,
    workspace: str | None = None,
    model: str | None = None,
    bindings: Iterable[str] = (),
    take_ownership: bool = False,
    container: str | None = None,
    ssh_host: str | None = None,
    adapter: OpenClawAdapter | None = None,
) -> OpenClawDeploymentPlan:
    adapter = adapter or OpenClawAdapter(container=container, ssh_host=ssh_host)
    doctor = adapter.doctor()
    if not doctor.available:
        raise OpenClawAdapterError(doctor.message)

    artifact = build_openclaw_overlay(package, agent=agent)
    resolved_agent = artifact.agent
    validate_agent_id(
        resolved_agent,
        explicit_main=agent_explicit and resolved_agent == "main",
    )
    existing = adapter.agent(resolved_agent)
    existing_agent = existing is not None
    if existing:
        resolved_workspace = _absolute_workspace(adapter, existing.workspace)
        if workspace and _absolute_workspace(adapter, workspace) != resolved_workspace:
            raise OpenClawAdapterError(
                f"OpenClaw reports workspace {resolved_workspace} for agent {resolved_agent}; "
                "the explicit --workspace does not match"
            )
    else:
        if resolved_agent == "main":
            raise OpenClawAdapterError("OpenClaw main agent was not returned by agents list; PersonaDock will not create it")
        if not workspace:
            raise OpenClawAdapterError(
                "creating a new OpenClaw agent requires an explicit --workspace; PersonaDock will not guess one"
            )
        resolved_workspace = _absolute_workspace(adapter, workspace)

    existing_manifest = _load_workspace_manifest(adapter, resolved_workspace) if existing else None
    conflicts = _ownership_conflicts(
        adapter,
        resolved_workspace,
        artifact,
        existing_manifest,
    )
    if conflicts and not take_ownership:
        raise OpenClawAdapterError(
            "workspace contains unmanaged persona files: "
            + ", ".join(conflicts)
            + "; pass --take-ownership only after reviewing the deployment plan"
        )

    deployment_id = str(uuid.uuid4())
    snapshot_path = None
    if existing_agent and (existing_manifest or conflicts):
        snapshot_path = str(
            registry_root()
            / "snapshots"
            / "openclaw"
            / resolved_agent
            / f"{_timestamp()}-{deployment_id[:8]}-pre-deploy"
        )

    commands: list[tuple[str, ...]] = []
    bindings_tuple = tuple(dict.fromkeys(str(item) for item in bindings if str(item)))
    if not existing_agent:
        add = [
            "agents",
            "add",
            resolved_agent,
            "--workspace",
            resolved_workspace,
            "--non-interactive",
            "--json",
        ]
        if model:
            add.extend(("--model", model))
        for binding in bindings_tuple:
            add.extend(("--bind", binding))
        commands.append(tuple(add))
    commands.append(
        (
            "workspace-overlay",
            artifact.path,
            resolved_workspace,
        )
    )
    commands.append(
        (
            "agents",
            "set-identity",
            "--agent",
            resolved_agent,
            "--from-identity",
            "--json",
        )
    )
    commands.append(("agents", "list", "--json", "--bindings"))

    warnings: list[str] = []
    if resolved_agent == "main":
        warnings.append("The reserved main OpenClaw agent was selected explicitly.")
    if conflicts:
        warnings.append(
            "PersonaDock will take ownership of existing workspace files: "
            + ", ".join(conflicts)
        )
    if not existing_agent:
        warnings.append(
            "OpenClaw will create a new Agent entry and its separate agentDir/state directory. PersonaDock does not write into agentDir."
        )
    return OpenClawDeploymentPlan(
        id=deployment_id,
        package=str(Path(package).expanduser().resolve()),
        persona_id=artifact.persona_id,
        persona_version=artifact.version,
        agent=resolved_agent,
        agent_explicit=agent_explicit,
        existing_agent=existing_agent,
        workspace=resolved_workspace,
        state_directory=existing.agent_dir if existing else None,
        container=container,
        ssh_host=ssh_host,
        model=model,
        bindings=bindings_tuple,
        take_ownership=take_ownership,
        artifact=artifact,
        snapshot_path=snapshot_path,
        conflicts=tuple(conflicts),
        commands=tuple(commands),
        preserves=(
            "AGENTS.md, USER.md, TOOLS.md, HEARTBEAT.md, and BOOTSTRAP.md",
            "MEMORY.md, memory/, and DREAMS.md",
            "workspace-local skills outside the PersonaDock-owned skill directory",
            "agentDir and OpenClaw configuration/state",
            "auth profiles, OAuth tokens, sessions, transcripts, routing, and memory indexes",
        ),
        warnings=tuple(warnings),
    )


def _remove_path(adapter: OpenClawAdapter, path: str) -> None:
    if adapter.runner.transport == "local":
        local = Path(path).expanduser().resolve()
        if local.is_dir():
            shutil.rmtree(local)
        elif local.exists():
            local.unlink()
    else:
        adapter.runner.shell(f"rm -rf {shlex_quote(path)}", check=True)


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def _snapshot_workspace(
    adapter: OpenClawAdapter,
    plan: OpenClawDeploymentPlan,
) -> str | None:
    if not plan.snapshot_path:
        return None
    root = Path(plan.snapshot_path)
    content = root / "content"
    content.mkdir(parents=True, exist_ok=False)
    candidates = set(plan.artifact.owned_paths)
    existing_manifest = _load_workspace_manifest(adapter, plan.workspace)
    if existing_manifest:
        candidates.update(
            str(item)
            for item in existing_manifest.get("owned_paths", [])
            if isinstance(item, str)
        )
    candidates.update(plan.conflicts)
    present: list[str] = []
    for relative in sorted(candidates):
        source = _workspace_path(adapter, plan.workspace, relative)
        if not adapter.runner.exists(source):
            continue
        target = content / Path(relative)
        adapter.runner.copy_from(source, target)
        present.append(relative)
    manifest = {
        "format": "personadock-openclaw-workspace-snapshot",
        "format_version": 1,
        "deployment_id": plan.id,
        "agent": plan.agent,
        "workspace": plan.workspace,
        "transport": plan.transport,
        "container": plan.container,
        "ssh_host": plan.ssh_host,
        "paths": present,
        "created_at": _utc_now(),
    }
    (root / "snapshot-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return str(root)


def _copy_overlay(adapter: OpenClawAdapter, plan: OpenClawDeploymentPlan) -> None:
    artifact_root = Path(plan.artifact.path)
    for path in sorted(artifact_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(artifact_root).as_posix()
        destination = _workspace_path(adapter, plan.workspace, relative)
        adapter.runner.write_text(
            destination,
            path.read_text(encoding="utf-8"),
        )


def _verify_overlay(
    adapter: OpenClawAdapter,
    plan: OpenClawDeploymentPlan,
) -> dict[str, Any]:
    artifact_root = Path(plan.artifact.path)
    verified: dict[str, str] = {}
    for path in sorted(artifact_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(artifact_root).as_posix()
        expected = sha256_file(path)
        actual_text = adapter.runner.read_text(
            _workspace_path(adapter, plan.workspace, relative)
        )
        if actual_text is None:
            raise OpenClawAdapterError(f"OpenClaw workspace verification is missing {relative}")
        actual = _sha256_text(actual_text)
        if actual != expected:
            raise OpenClawAdapterError(f"OpenClaw workspace checksum mismatch: {relative}")
        verified[relative] = actual
    agents = adapter.list_agents()
    deployed = next((item for item in agents if item.id == plan.agent), None)
    if deployed is None:
        raise OpenClawAdapterError(f"OpenClaw did not report deployed agent: {plan.agent}")
    if _absolute_workspace(adapter, deployed.workspace) != plan.workspace:
        raise OpenClawAdapterError(
            f"OpenClaw reported unexpected workspace for {plan.agent}: {deployed.workspace}"
        )
    return {
        "files": verified,
        "agent": deployed.to_dict(),
    }


def _restore_workspace_snapshot(
    adapter: OpenClawAdapter,
    plan: OpenClawDeploymentPlan,
    snapshot: str,
) -> None:
    root = Path(snapshot)
    manifest = json.loads((root / "snapshot-manifest.json").read_text(encoding="utf-8"))
    current_manifest = _load_workspace_manifest(adapter, plan.workspace)
    remove_paths = set(plan.artifact.owned_paths)
    if current_manifest:
        remove_paths.update(
            str(item)
            for item in current_manifest.get("owned_paths", [])
            if isinstance(item, str)
        )
    for relative in sorted(remove_paths, key=lambda value: len(Path(value).parts), reverse=True):
        _remove_path(adapter, _workspace_path(adapter, plan.workspace, relative))
    for relative in manifest.get("paths", []):
        source = root / "content" / Path(relative)
        destination = _workspace_path(adapter, plan.workspace, str(relative))
        adapter.runner.copy_to(source, destination)
    adapter.runner.run(
        ["agents", "set-identity", "--agent", plan.agent, "--from-identity", "--json"],
        timeout=60,
    )


def _record_snapshot(
    service: RegistryService,
    *,
    plan: OpenClawDeploymentPlan,
    runtime_instance_id: str | None,
    snapshot: str,
) -> None:
    with service.database.session() as connection:
        connection.execute(
            """
            INSERT INTO snapshots(
                id, persona_id, runtime_instance_id, kind, path, metadata_json, created_at
            ) VALUES(?, ?, ?, 'pre-deployment', ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                plan.persona_id if service.get_persona(plan.persona_id) else None,
                runtime_instance_id,
                snapshot,
                json.dumps(
                    {
                        "deployment_id": plan.id,
                        "agent": plan.agent,
                        "workspace": plan.workspace,
                        "transport": plan.transport,
                        "container": plan.container,
                        "ssh_host": plan.ssh_host,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                _utc_now(),
            ),
        )


def _mark_deployed(
    service: RegistryService,
    *,
    persona_id: str,
    runtime_instance_id: str,
    version: str,
) -> None:
    binding = service.bind(persona_id, runtime_instance_id, adopted=False)
    with service.database.session() as connection:
        connection.execute(
            "UPDATE bindings SET last_deployed_version = ? WHERE id = ?",
            (version, binding.id),
        )


def apply_openclaw_deployment(
    plan: OpenClawDeploymentPlan,
    *,
    adapter: OpenClawAdapter | None = None,
    registry: RegistryService | None = None,
) -> OpenClawDeploymentResult:
    adapter = adapter or OpenClawAdapter(container=plan.container, ssh_host=plan.ssh_host)
    service = registry or RegistryService()
    snapshot: str | None = None
    created = False
    try:
        snapshot = _snapshot_workspace(adapter, plan)
        if not plan.existing_agent:
            command = [
                "agents",
                "add",
                plan.agent,
                "--workspace",
                plan.workspace,
                "--non-interactive",
                "--json",
            ]
            if plan.model:
                command.extend(("--model", plan.model))
            for binding in plan.bindings:
                command.extend(("--bind", binding))
            adapter.runner.run(command, check=True, timeout=180)
            created = True
        _copy_overlay(adapter, plan)
        adapter.runner.run(
            ["agents", "set-identity", "--agent", plan.agent, "--from-identity", "--json"],
            check=True,
            timeout=90,
        )
        verification = _verify_overlay(adapter, plan)
        deployed_agent = verification["agent"]
        instance = service.upsert_runtime_instance(
            adapter="openclaw",
            transport=plan.transport,
            platform_instance_id=plan.agent,
            display_name=str(
                (deployed_agent.get("identity") or {}).get("name")
                or deployed_agent.get("name")
                or plan.agent
            ),
            location=plan.workspace,
            capabilities={
                "native_agent": True,
                "native_deployment": True,
                "memory_pull": True,
                "memory_push": True,
                "session_summary_pull": False,
            },
            metadata={
                "discovery_source": "personadock-native-deployment",
                "workspace": plan.workspace,
                "agent_dir": deployed_agent.get("agent_dir"),
                "identity": deployed_agent.get("identity", {}),
                "bindings": deployed_agent.get("bindings", []),
                "container": plan.container,
                "ssh_host": plan.ssh_host,
                "ownership_manifest": "personadock-manifest.json",
            },
        )
        persona = service.get_persona(plan.persona_id)
        if persona:
            _mark_deployed(
                service,
                persona_id=plan.persona_id,
                runtime_instance_id=instance.id,
                version=plan.persona_version,
            )
        if snapshot:
            _record_snapshot(
                service,
                plan=plan,
                runtime_instance_id=instance.id,
                snapshot=snapshot,
            )
        service.journal(
            "openclaw-native-deployed",
            persona_id=plan.persona_id if persona else None,
            runtime_instance_id=instance.id,
            payload={
                "deployment_id": plan.id,
                "agent": plan.agent,
                "workspace": plan.workspace,
                "state_directory": deployed_agent.get("agent_dir"),
                "version": plan.persona_version,
                "snapshot": snapshot,
                "created_agent": created,
                "transport": plan.transport,
            },
        )
        return OpenClawDeploymentResult(
            deployment_id=plan.id,
            persona_id=plan.persona_id,
            persona_version=plan.persona_version,
            agent=plan.agent,
            workspace=plan.workspace,
            state_directory=deployed_agent.get("agent_dir"),
            transport=plan.transport,
            container=plan.container,
            ssh_host=plan.ssh_host,
            snapshot_path=snapshot,
            created_agent=created,
            verification=verification,
        )
    except Exception:
        try:
            if created:
                adapter.runner.run(
                    ["agents", "delete", plan.agent, "--force", "--json"],
                    timeout=180,
                )
            elif snapshot:
                _restore_workspace_snapshot(adapter, plan, snapshot)
        except Exception as rollback_error:
            raise OpenClawAdapterError(
                f"OpenClaw deployment failed and rollback also failed: {rollback_error}"
            ) from rollback_error
        raise


def rollback_openclaw_deployment(
    *,
    agent: str,
    snapshot: str | Path | None,
    workspace: str | None = None,
    delete_agent: bool = False,
    container: str | None = None,
    ssh_host: str | None = None,
    adapter: OpenClawAdapter | None = None,
    registry: RegistryService | None = None,
) -> dict[str, Any]:
    adapter = adapter or OpenClawAdapter(container=container, ssh_host=ssh_host)
    service = registry or RegistryService()
    current = adapter.agent(agent)
    if current is None:
        raise OpenClawAdapterError(f"OpenClaw agent does not exist: {agent}")
    resolved_workspace = _absolute_workspace(adapter, current.workspace)
    if workspace and _absolute_workspace(adapter, workspace) != resolved_workspace:
        raise OpenClawAdapterError("explicit workspace does not match OpenClaw agent workspace")
    if delete_agent:
        if agent == "main":
            raise OpenClawAdapterError("OpenClaw main agent cannot be deleted")
        adapter.runner.run(
            ["agents", "delete", agent, "--force", "--json"],
            check=True,
            timeout=180,
        )
        action = "deleted-agent"
    else:
        if snapshot is None:
            raise OpenClawAdapterError("workspace rollback requires --snapshot or --delete-agent")
        snapshot_path = Path(snapshot).expanduser().resolve()
        if not (snapshot_path / "snapshot-manifest.json").is_file():
            raise OpenClawAdapterError(f"invalid OpenClaw snapshot: {snapshot_path}")
        overlay_manifest = _load_workspace_manifest(adapter, resolved_workspace) or {}
        artifact = OpenClawOverlayArtifact(
            path="",
            persona_id=str(overlay_manifest.get("persona_id") or "unknown"),
            version=str(overlay_manifest.get("persona_version") or "unknown"),
            agent=agent,
            skill_id="persona",
            package="",
            package_sha256="",
            owned_paths=tuple(
                str(item)
                for item in overlay_manifest.get("owned_paths", [])
                if isinstance(item, str)
            ),
        )
        plan = OpenClawDeploymentPlan(
            id=str(uuid.uuid4()),
            package="",
            persona_id=artifact.persona_id,
            persona_version=artifact.version,
            agent=agent,
            agent_explicit=True,
            existing_agent=True,
            workspace=resolved_workspace,
            state_directory=current.agent_dir,
            container=container,
            ssh_host=ssh_host,
            model=None,
            bindings=(),
            take_ownership=False,
            artifact=artifact,
            snapshot_path=str(snapshot_path),
            conflicts=(),
            commands=(),
            preserves=(),
            warnings=(),
        )
        _restore_workspace_snapshot(adapter, plan, str(snapshot_path))
        action = "restored-workspace"
    service.journal(
        "openclaw-native-rolled-back",
        payload={
            "agent": agent,
            "workspace": resolved_workspace,
            "snapshot": str(snapshot) if snapshot else None,
            "delete_agent": delete_agent,
            "transport": adapter.runner.transport,
        },
    )
    return {
        "agent": agent,
        "workspace": resolved_workspace,
        "snapshot": str(snapshot) if snapshot else None,
        "action": action,
        "transport": adapter.runner.transport,
    }
