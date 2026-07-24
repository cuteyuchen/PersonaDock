from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from persona_dock.packaging import inspect_package
from persona_dock.targeting import DetectedTarget, resolve_local_target


@dataclass(frozen=True)
class DeploymentOperation:
    action: str
    source: str
    destination: str
    exists: bool | None
    ownership: str = "personadock"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeploymentPlan:
    package: str
    package_id: str
    package_version: str
    target: str
    adapter: str
    transport: str
    destination: str
    destination_source: str
    container: str | None
    operations: tuple[DeploymentOperation, ...]
    preserves: tuple[str, ...]
    warnings: tuple[str, ...]
    requires_confirmation: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["operations"] = [operation.to_dict() for operation in self.operations]
        return value


def _target_files(info: dict[str, Any], target: str) -> list[str]:
    prefix = f"targets/{target}/"
    return sorted(
        name[len(prefix) :]
        for name in info.get("files", {})
        if name.startswith(prefix) and name != prefix
    )


def _local_operations(files: list[str], destination: Path) -> tuple[DeploymentOperation, ...]:
    return tuple(
        DeploymentOperation(
            action="copy",
            source=relative,
            destination=str(destination / Path(relative)),
            exists=(destination / Path(relative)).exists(),
        )
        for relative in files
    )


def _container_operations(
    files: list[str],
    destination: PurePosixPath,
) -> tuple[DeploymentOperation, ...]:
    return tuple(
        DeploymentOperation(
            action="copy",
            source=relative,
            destination=str(destination / PurePosixPath(relative)),
            exists=None,
        )
        for relative in files
    )


def build_deployment_plan(
    package: Path,
    target: str,
    destination: str | Path | None = None,
    container: str | None = None,
) -> DeploymentPlan:
    package = package.expanduser().resolve()
    info = inspect_package(package)
    if info.get("integrity") != "ok":
        raise ValueError("PersonaPack integrity check failed")
    if target not in info.get("targets", {}):
        raise ValueError(f"package does not contain target {target}")

    files = _target_files(info, target)
    if not files:
        raise ValueError(f"package target {target} contains no deployable files")

    warnings = [
        "Phase 0 uses the legacy filesystem adapter; native Hermes/OpenClaw adapters are not active yet.",
        "Review this plan before applying it. Runtime memories, sessions, credentials, and platform configuration are not owned by PersonaDock.",
    ]

    if container:
        if destination is None:
            raise ValueError(
                "legacy Docker deployment requires an explicit absolute --path inside the container"
            )
        value = str(destination).strip().replace("\\", "/")
        resolved_container = PurePosixPath(value)
        if not resolved_container.is_absolute():
            raise ValueError("Docker deployment --path must be an absolute container path")
        operations = _container_operations(files, resolved_container)
        destination_value = str(resolved_container)
        destination_source = "explicit-container-path"
        transport = "docker"
    else:
        detected: DetectedTarget = resolve_local_target(target, destination)
        operations = _local_operations(files, detected.path)
        destination_value = str(detected.path)
        destination_source = detected.source
        transport = "local"
        if detected.source != "explicit-path" and target != "generic":
            warnings.append(
                f"Target was detected from {detected.source} with confidence {detected.confidence}; pass --path to override it."
            )

    preserves = (
        "credentials and API keys",
        "platform sessions",
        "platform-local memories not listed in the PersonaPack",
        "platform configuration outside PersonaDock-owned files",
        "unrelated skills",
    )
    return DeploymentPlan(
        package=str(package),
        package_id=str(info.get("id", "unknown")),
        package_version=str(info.get("version", "unknown")),
        target=target,
        adapter="legacy-filesystem",
        transport=transport,
        destination=destination_value,
        destination_source=destination_source,
        container=container,
        operations=operations,
        preserves=preserves,
        warnings=tuple(warnings),
        metadata={
            "package_sha256": info.get("package_sha256"),
            "integrity": info.get("integrity"),
        },
    )


def apply_deployment_plan(plan: DeploymentPlan) -> Path | PurePosixPath:
    from persona_dock.installer import install_package

    destination: str | Path
    if plan.transport == "docker":
        destination = plan.destination
    else:
        destination = Path(plan.destination)
    return install_package(
        Path(plan.package),
        plan.target,
        destination,
        plan.container,
    )
