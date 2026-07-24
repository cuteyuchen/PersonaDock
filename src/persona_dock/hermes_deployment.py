from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from persona_dock.adapters.hermes import (
    HermesAdapter,
    HermesAdapterError,
    parse_key_values,
    validate_profile_name,
)
from persona_dock.io import dump_yaml, sha256_file
from persona_dock.packaging import inspect_package
from persona_dock.registry import RegistryService
from persona_dock.registry.database import registry_root


@dataclass(frozen=True)
class HermesDistributionArtifact:
    path: str
    persona_id: str
    version: str
    profile: str
    package: str
    package_sha256: str
    owned_files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HermesDeploymentPlan:
    id: str
    package: str
    persona_id: str
    persona_version: str
    profile: str
    profile_explicit: bool
    existing_profile: bool
    activate: bool
    alias: bool
    container: str | None
    artifact: HermesDistributionArtifact
    snapshot_path: str | None
    commands: tuple[tuple[str, ...], ...]
    preserves: tuple[str, ...]
    warnings: tuple[str, ...]
    requires_confirmation: bool = True

    @property
    def transport(self) -> str:
        return "docker" if self.container else "local"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["transport"] = self.transport
        value["artifact"] = self.artifact.to_dict()
        value["commands"] = [list(command) for command in self.commands]
        return value


@dataclass(frozen=True)
class HermesDeploymentResult:
    deployment_id: str
    persona_id: str
    persona_version: str
    profile: str
    transport: str
    container: str | None
    snapshot_path: str | None
    profile_path: str | None
    active: bool
    verification: dict[str, Any]
    rolled_back: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_hermes_distribution(
    package: str | Path,
    *,
    profile: str | None = None,
    output: Path | None = None,
) -> HermesDistributionArtifact:
    package_path = Path(package).expanduser().resolve()
    info = inspect_package(package_path)
    if info.get("integrity") != "ok":
        raise HermesAdapterError("PersonaPack integrity check failed")
    if "hermes" not in info.get("targets", {}):
        raise HermesAdapterError("PersonaPack does not contain a Hermes target")

    persona_id = str(info.get("id") or "persona")
    version = str(info.get("version") or "0.0.0")
    resolved_profile = profile or persona_id
    validate_profile_name(
        resolved_profile,
        explicit_default=profile is not None and resolved_profile == "default",
    )

    destination = (
        output.expanduser().resolve()
        if output
        else registry_root()
        / "artifacts"
        / "hermes"
        / persona_id
        / version
        / resolved_profile
    )
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    prefix = "targets/hermes/"
    copied: list[str] = []
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if prefix + "SOUL.md" not in names:
            raise HermesAdapterError("Hermes target is missing SOUL.md")
        for member in archive.infolist():
            if member.is_dir() or not member.filename.startswith(prefix):
                continue
            relative = member.filename[len(prefix) :]
            if not relative or relative.startswith("memory/"):
                continue
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise HermesAdapterError(f"unsafe PersonaPack path: {member.filename}")
            if relative != "SOUL.md" and not relative.startswith("skills/"):
                continue
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
            copied.append(relative)

    owned = ["SOUL.md", "skills/", "distribution.yaml", "personadock-manifest.json"]
    distribution = {
        "name": persona_id,
        "version": version,
        "description": str(info.get("summary") or f"PersonaDock persona {persona_id}"),
        "hermes_requires": ">=0.12.0",
        "author": "PersonaDock",
        "license": "MIT",
        "distribution_owned": owned,
    }
    (destination / "distribution.yaml").write_text(
        dump_yaml(distribution),
        encoding="utf-8",
    )
    manifest = {
        "format": "personadock-hermes-distribution",
        "format_version": 1,
        "persona_id": persona_id,
        "persona_version": version,
        "target_profile": resolved_profile,
        "source_package": str(package_path),
        "source_package_sha256": str(info.get("package_sha256") or sha256_file(package_path)),
        "generated_at": _utc_now(),
        "owned_files": owned,
        "excluded": [
            ".env",
            "auth.json",
            "memories/",
            "sessions/",
            "state.db*",
            "logs/",
            "workspace/",
            "plans/",
            "home/",
            "*_cache/",
            "local/",
        ],
    }
    (destination / "personadock-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    copied.extend(("distribution.yaml", "personadock-manifest.json"))
    return HermesDistributionArtifact(
        path=str(destination),
        persona_id=persona_id,
        version=version,
        profile=resolved_profile,
        package=str(package_path),
        package_sha256=str(info.get("package_sha256") or sha256_file(package_path)),
        owned_files=tuple(sorted(copied)),
    )


def plan_hermes_deployment(
    package: str | Path,
    *,
    profile: str | None = None,
    profile_explicit: bool = False,
    activate: bool = False,
    alias: bool = False,
    container: str | None = None,
    adapter: HermesAdapter | None = None,
) -> HermesDeploymentPlan:
    adapter = adapter or HermesAdapter(container=container)
    doctor = adapter.doctor()
    if not doctor.available:
        raise HermesAdapterError(doctor.message)

    artifact = build_hermes_distribution(package, profile=profile)
    resolved_profile = artifact.profile
    validate_profile_name(
        resolved_profile,
        explicit_default=profile_explicit and resolved_profile == "default",
    )
    existing = adapter.profile(resolved_profile) is not None
    deployment_id = str(uuid.uuid4())
    snapshot_path = None
    if existing:
        snapshot_path = str(
            registry_root()
            / "snapshots"
            / "hermes"
            / resolved_profile
            / f"{_timestamp()}-{deployment_id[:8]}-pre-deploy.tar.gz"
        )

    source = artifact.path if not container else f"/tmp/personadock-{deployment_id}"
    install = ["profile", "install", source, "--name", resolved_profile, "--yes"]
    if existing:
        install.append("--force")
    if alias:
        install.append("--alias")
    commands: list[tuple[str, ...]] = []
    if existing:
        snapshot_command_path = snapshot_path or "snapshot.tar.gz"
        if container:
            snapshot_command_path = f"/tmp/personadock-{deployment_id}-snapshot.tar.gz"
        commands.append(
            ("profile", "export", resolved_profile, "-o", snapshot_command_path)
        )
    commands.append(tuple(install))
    if activate:
        commands.append(("profile", "use", resolved_profile))
    commands.extend(
        [
            ("profile", "show", resolved_profile),
            ("profile", "info", resolved_profile),
        ]
    )

    warnings: list[str] = []
    if resolved_profile == "default":
        warnings.append(
            "The default Hermes profile was selected explicitly and will be updated."
        )
    if existing:
        warnings.append(
            "The existing profile will be exported before Hermes applies the distribution."
        )
    if container:
        warnings.append(
            "The distribution will be copied into the container and installed by the Hermes CLI there."
        )
    return HermesDeploymentPlan(
        id=deployment_id,
        package=str(Path(package).expanduser().resolve()),
        persona_id=artifact.persona_id,
        persona_version=artifact.version,
        profile=resolved_profile,
        profile_explicit=profile_explicit,
        existing_profile=existing,
        activate=activate,
        alias=alias,
        container=container,
        artifact=artifact,
        snapshot_path=snapshot_path,
        commands=tuple(commands),
        preserves=(
            "Hermes memories/",
            "Hermes sessions/",
            "Hermes .env",
            "Hermes auth.json and provider credentials",
            "Hermes state.db and runtime state",
            "config.yaml local overrides",
            "local and unrelated skills outside distribution-owned paths",
        ),
        warnings=tuple(warnings),
    )


def _run_host_command(command: list[str], *, timeout: int = 60) -> None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
        raise HermesAdapterError(f"failed to run {' '.join(command)}: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise HermesAdapterError(detail)


def _prepare_container_artifact(
    adapter: HermesAdapter,
    plan: HermesDeploymentPlan,
) -> str:
    if not adapter.container:
        raise HermesAdapterError("container artifact preparation requires a container")
    remote = f"/tmp/personadock-{plan.id}"
    _run_host_command(
        [
            adapter.runner.docker_executable,
            "exec",
            adapter.container,
            "sh",
            "-lc",
            f"rm -rf {shlex.quote(remote)} && mkdir -p {shlex.quote(remote)}",
        ]
    )
    adapter.runner.docker_copy_to(str(Path(plan.artifact.path)) + "/.", remote)
    return remote


def _cleanup_container(adapter: HermesAdapter, plan: HermesDeploymentPlan) -> None:
    if not adapter.container:
        return
    paths = [
        f"/tmp/personadock-{plan.id}",
        f"/tmp/personadock-{plan.id}-snapshot.tar.gz",
        f"/tmp/personadock-{plan.id}-rollback.tar.gz",
    ]
    command = "rm -rf " + " ".join(shlex.quote(path) for path in paths)
    try:
        _run_host_command(
            [
                adapter.runner.docker_executable,
                "exec",
                adapter.container,
                "sh",
                "-lc",
                command,
            ],
            timeout=30,
        )
    except HermesAdapterError:
        pass


def _snapshot_existing_profile(
    adapter: HermesAdapter,
    plan: HermesDeploymentPlan,
) -> str | None:
    if not plan.existing_profile or not plan.snapshot_path:
        return None
    local = Path(plan.snapshot_path)
    local.parent.mkdir(parents=True, exist_ok=True)
    if adapter.container:
        remote = f"/tmp/personadock-{plan.id}-snapshot.tar.gz"
        adapter.runner.run(
            ["profile", "export", plan.profile, "-o", remote],
            check=True,
            timeout=120,
        )
        adapter.runner.docker_copy_from(remote, local)
    else:
        adapter.runner.run(
            ["profile", "export", plan.profile, "-o", str(local)],
            check=True,
            timeout=120,
        )
    if not local.is_file() or local.stat().st_size == 0:
        raise HermesAdapterError(
            "Hermes did not create a usable pre-deployment profile snapshot"
        )
    return str(local)


def _restore_snapshot(
    adapter: HermesAdapter,
    *,
    profile: str,
    snapshot: Path,
    deployment_id: str,
) -> None:
    if adapter.container:
        remote = f"/tmp/personadock-{deployment_id}-rollback.tar.gz"
        adapter.runner.docker_copy_to(snapshot, remote)
        adapter.runner.run(
            ["profile", "import", remote, "--name", profile],
            check=True,
            timeout=180,
        )
    else:
        adapter.runner.run(
            ["profile", "import", str(snapshot), "--name", profile],
            check=True,
            timeout=180,
        )


def _rollback_failed_apply(
    adapter: HermesAdapter,
    plan: HermesDeploymentPlan,
    snapshot: str | None,
) -> None:
    adapter.runner.run(
        ["profile", "delete", plan.profile, "--yes"],
        timeout=120,
    )
    if snapshot:
        _restore_snapshot(
            adapter,
            profile=plan.profile,
            snapshot=Path(snapshot),
            deployment_id=plan.id,
        )


def _record_snapshot(
    service: RegistryService,
    *,
    snapshot_id: str,
    persona_id: str,
    runtime_instance_id: str | None,
    path: str,
    metadata: dict[str, Any],
) -> None:
    registered_persona = service.get_persona(persona_id)
    with service.database.session() as connection:
        connection.execute(
            """
            INSERT INTO snapshots(
                id, persona_id, runtime_instance_id, kind, path, metadata_json, created_at
            ) VALUES(?, ?, ?, 'pre-deployment', ?, ?, ?)
            """,
            (
                snapshot_id,
                persona_id if registered_persona else None,
                runtime_instance_id,
                path,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
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


def apply_hermes_deployment(
    plan: HermesDeploymentPlan,
    *,
    adapter: HermesAdapter | None = None,
    registry: RegistryService | None = None,
) -> HermesDeploymentResult:
    adapter = adapter or HermesAdapter(container=plan.container)
    service = registry or RegistryService()
    snapshot: str | None = None
    try:
        snapshot = _snapshot_existing_profile(adapter, plan)
        source = plan.artifact.path
        if plan.container:
            source = _prepare_container_artifact(adapter, plan)

        install = [
            "profile",
            "install",
            source,
            "--name",
            plan.profile,
            "--yes",
        ]
        if plan.existing_profile:
            install.append("--force")
        if plan.alias:
            install.append("--alias")
        adapter.runner.run(install, check=True, timeout=240)

        if plan.activate:
            adapter.runner.run(
                ["profile", "use", plan.profile],
                check=True,
                timeout=45,
            )

        show = adapter.runner.run(
            ["profile", "show", plan.profile],
            check=True,
            timeout=45,
        )
        info = adapter.runner.run(
            ["profile", "info", plan.profile],
            check=True,
            timeout=45,
        )
        details = parse_key_values(show.stdout)
        distribution = parse_key_values(info.stdout)
        installed_version = distribution.get("version")
        if installed_version and installed_version != plan.persona_version:
            raise HermesAdapterError(
                f"Hermes reported distribution version {installed_version}, "
                f"expected {plan.persona_version}"
            )
        profile_path = (
            details.get("path")
            or details.get("home")
            or details.get("home_directory")
        )
        location = profile_path or (
            f"docker://{plan.container}/profile/{plan.profile}"
            if plan.container
            else f"hermes-profile://{plan.profile}"
        )
        instance = service.upsert_runtime_instance(
            adapter="hermes",
            transport=plan.transport,
            platform_instance_id=plan.profile,
            display_name=plan.profile,
            location=location,
            capabilities={
                "native_profile": True,
                "native_deployment": True,
                "memory_pull": True,
                "memory_push": True,
                "session_summary_pull": False,
            },
            metadata={
                "discovery_source": "personadock-native-deployment",
                "active": plan.activate,
                "profile_details": details,
                "distribution": distribution,
                "container": plan.container,
            },
        )
        registered_persona = service.get_persona(plan.persona_id)
        if registered_persona:
            _mark_deployed(
                service,
                persona_id=plan.persona_id,
                runtime_instance_id=instance.id,
                version=plan.persona_version,
            )
        if snapshot:
            _record_snapshot(
                service,
                snapshot_id=str(uuid.uuid4()),
                persona_id=plan.persona_id,
                runtime_instance_id=instance.id,
                path=snapshot,
                metadata={
                    "deployment_id": plan.id,
                    "profile": plan.profile,
                    "transport": plan.transport,
                    "container": plan.container,
                },
            )
        service.journal(
            "hermes-native-deployed",
            persona_id=plan.persona_id if registered_persona else None,
            runtime_instance_id=instance.id,
            payload={
                "deployment_id": plan.id,
                "version": plan.persona_version,
                "profile": plan.profile,
                "container": plan.container,
                "snapshot": snapshot,
                "activate": plan.activate,
                "alias": plan.alias,
            },
        )
        return HermesDeploymentResult(
            deployment_id=plan.id,
            persona_id=plan.persona_id,
            persona_version=plan.persona_version,
            profile=plan.profile,
            transport=plan.transport,
            container=plan.container,
            snapshot_path=snapshot,
            profile_path=profile_path,
            active=plan.activate,
            verification={
                "show": details,
                "distribution": distribution,
                "commands": [show.to_dict(), info.to_dict()],
            },
        )
    except Exception:
        try:
            _rollback_failed_apply(adapter, plan, snapshot)
        except Exception as rollback_error:
            raise HermesAdapterError(
                f"Hermes deployment failed and rollback also failed: {rollback_error}"
            ) from rollback_error
        raise
    finally:
        _cleanup_container(adapter, plan)


def rollback_hermes_deployment(
    *,
    profile: str,
    snapshot: str | Path | None,
    container: str | None = None,
    activate: bool = False,
    adapter: HermesAdapter | None = None,
    registry: RegistryService | None = None,
) -> dict[str, Any]:
    adapter = adapter or HermesAdapter(container=container)
    service = registry or RegistryService()
    adapter.runner.run(
        ["profile", "delete", profile, "--yes"],
        timeout=120,
    )
    action = "deleted"
    resolved_snapshot: Path | None = None
    deployment_id = str(uuid.uuid4())
    if snapshot is not None:
        resolved_snapshot = Path(snapshot).expanduser().resolve()
        if not resolved_snapshot.is_file():
            raise HermesAdapterError(
                f"rollback snapshot does not exist: {resolved_snapshot}"
            )
        _restore_snapshot(
            adapter,
            profile=profile,
            snapshot=resolved_snapshot,
            deployment_id=deployment_id,
        )
        action = "restored"
    if activate and resolved_snapshot:
        adapter.runner.run(
            ["profile", "use", profile],
            check=True,
            timeout=45,
        )
    verification = (
        adapter.runner.run(["profile", "show", profile])
        if resolved_snapshot
        else None
    )
    service.journal(
        "hermes-native-rolled-back",
        payload={
            "profile": profile,
            "snapshot": str(resolved_snapshot) if resolved_snapshot else None,
            "container": container,
            "action": action,
        },
    )
    return {
        "profile": profile,
        "container": container,
        "action": action,
        "snapshot": str(resolved_snapshot) if resolved_snapshot else None,
        "verification": verification.to_dict() if verification else None,
    }
