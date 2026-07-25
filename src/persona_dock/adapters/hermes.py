from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from os import PathLike
from typing import Any, Iterable

from persona_dock.adapters.base import (
    AdapterCapabilities,
    AdapterDoctorResult,
    PersonaAdapter,
)


class HermesAdapterError(RuntimeError):
    """Raised when a native Hermes operation cannot be completed safely."""


@dataclass(frozen=True)
class HermesCommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HermesProfile:
    name: str
    active: bool
    path: str | None
    details: dict[str, str] = field(default_factory=dict)
    distribution: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION = re.compile(r"(?<!\d)(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)")
_RESERVED_PROFILE_NAMES = {"hermes", "test", "tmp", "root", "sudo"}


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        match = re.match(r"^\s*([^:]+):\s*(.*?)\s*$", raw)
        if match:
            values[match.group(1).strip().lower().replace(" ", "_")] = match.group(2).strip()
    return values


def parse_profile_names(text: str) -> list[tuple[str, bool]]:
    values: dict[str, bool] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or set(line) <= {"-", "=", "+", "|", " "}:
            continue
        if line.lower().startswith(("profile", "name ", "profiles")):
            continue
        active = line.startswith("*")
        line = line.lstrip("* ").strip()
        candidate = line.split("|", 1)[0].strip().split()[0] if line else ""
        if _PROFILE_NAME.fullmatch(candidate):
            values[candidate] = values.get(candidate, False) or active
    return sorted(values.items(), key=lambda item: (item[0] != "default", item[0].lower()))


def version_from_text(text: str) -> str | None:
    match = _VERSION.search(text)
    return match.group(1) if match else None


def validate_profile_name(name: str, *, explicit_default: bool) -> None:
    if not _PROFILE_NAME.fullmatch(name):
        raise HermesAdapterError(
            "Hermes profile name must start with a letter or digit and contain only letters, digits, '.', '_' or '-'"
        )
    if name.lower() in _RESERVED_PROFILE_NAMES:
        raise HermesAdapterError(f"Hermes reserves the profile name: {name}")
    if name == "default" and not explicit_default:
        raise HermesAdapterError(
            "PersonaDock will not target the default Hermes profile implicitly; pass --profile default explicitly"
        )


def _quote_command(command: Iterable[str]) -> str:
    return " ".join(shlex.quote(item) for item in command)


class HermesCommandRunner:
    def __init__(
        self,
        *,
        executable: str | None = None,
        container: str | None = None,
        docker_executable: str | None = None,
    ) -> None:
        self.container = container
        self.executable = executable or shutil.which("hermes") or "hermes"
        self.docker_executable = docker_executable or shutil.which("docker") or "docker"

    def command(self, arguments: Iterable[str]) -> list[str]:
        values = list(arguments)
        if self.container:
            return [self.docker_executable, "exec", self.container, "hermes", *values]
        return [self.executable, *values]

    def run(
        self,
        arguments: Iterable[str],
        *,
        timeout: int = 45,
        check: bool = False,
    ) -> HermesCommandResult:
        command = self.command(arguments)
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
            raise HermesAdapterError(f"failed to run {_quote_command(command)}: {error}") from error
        result = HermesCommandResult(
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and not result.ok:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise HermesAdapterError(f"{_quote_command(command)} failed: {detail}")
        return result

    def docker_copy_to(self, source: PathLike[str] | str, destination: str) -> None:
        if not self.container:
            raise HermesAdapterError("docker_copy_to requires a Docker container")
        command = [
            self.docker_executable,
            "cp",
            str(source),
            f"{self.container}:{destination}",
        ]
        self._run_docker_copy(command)

    def docker_copy_from(self, source: str, destination: PathLike[str] | str) -> None:
        if not self.container:
            raise HermesAdapterError("docker_copy_from requires a Docker container")
        command = [
            self.docker_executable,
            "cp",
            f"{self.container}:{source}",
            str(destination),
        ]
        self._run_docker_copy(command)

    @staticmethod
    def _run_docker_copy(command: list[str]) -> None:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
            raise HermesAdapterError(f"failed to run {_quote_command(command)}: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "docker cp failed"
            raise HermesAdapterError(f"{_quote_command(command)} failed: {detail}")


class HermesAdapter(PersonaAdapter):
    name = "hermes"

    def __init__(
        self,
        *,
        executable: str | None = None,
        container: str | None = None,
        docker_executable: str | None = None,
    ) -> None:
        self.runner = HermesCommandRunner(
            executable=executable,
            container=container,
            docker_executable=docker_executable,
        )
        self.container = container

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            discovery=True,
            native_deployment=True,
            filesystem_deployment=False,
            memory_pull=True,
            memory_push=True,
            session_summary_pull=False,
            raw_session_import=False,
            docker=True,
        )

    def doctor(self) -> AdapterDoctorResult:
        executable = (
            self.runner.executable
            if not self.container
            else f"docker exec {self.container} hermes"
        )
        details = {
            "container": self.container,
            "native": True,
            "transport": "docker" if self.container else "local",
        }
        try:
            version_result = self.runner.run(["version"], timeout=15)
        except HermesAdapterError as error:
            return AdapterDoctorResult(
                adapter=self.name,
                available=False,
                executable=executable,
                version=None,
                status="unavailable",
                message=str(error),
                capabilities=self.capabilities,
                details=details,
            )
        version_text = "\n".join((version_result.stdout, version_result.stderr))
        version = version_from_text(version_text)
        if not version_result.ok:
            return AdapterDoctorResult(
                adapter=self.name,
                available=False,
                executable=executable,
                version=version,
                status="unavailable",
                message=version_result.stderr.strip()
                or version_result.stdout.strip()
                or "Hermes version failed",
                capabilities=self.capabilities,
                details=details,
            )
        try:
            profiles = self.runner.run(["profile", "list"], timeout=20)
        except HermesAdapterError as error:
            return AdapterDoctorResult(
                adapter=self.name,
                available=False,
                executable=executable,
                version=version,
                status="degraded",
                message=str(error),
                capabilities=self.capabilities,
                details=details,
            )
        if not profiles.ok:
            return AdapterDoctorResult(
                adapter=self.name,
                available=False,
                executable=executable,
                version=version,
                status="degraded",
                message=profiles.stderr.strip()
                or profiles.stdout.strip()
                or "Hermes profile list failed",
                capabilities=self.capabilities,
                details=details,
            )
        details["profile_count"] = len(parse_profile_names(profiles.stdout))
        details["minimum_distribution_version"] = "0.12.0"
        return AdapterDoctorResult(
            adapter=self.name,
            available=True,
            executable=executable,
            version=version,
            status="ready",
            message="Hermes CLI and native Profile Distribution commands are available.",
            capabilities=self.capabilities,
            details=details,
        )

    def list_profiles(self) -> list[HermesProfile]:
        result = self.runner.run(["profile", "list"], check=True)
        profiles: list[HermesProfile] = []
        for name, active in parse_profile_names(result.stdout):
            show = self.runner.run(["profile", "show", name])
            details = parse_key_values(show.stdout) if show.ok else {}
            info = self.runner.run(["profile", "info", name])
            distribution = parse_key_values(info.stdout) if info.ok else {}
            profiles.append(
                HermesProfile(
                    name=name,
                    active=active,
                    path=details.get("path")
                    or details.get("home")
                    or details.get("home_directory"),
                    details=details,
                    distribution=distribution,
                )
            )
        return profiles

    def profile(self, name: str) -> HermesProfile | None:
        return next((value for value in self.list_profiles() if value.name == name), None)

    def plan_deployment(
        self,
        package: str,
        *,
        destination: str | None = None,
        container: str | None = None,
    ) -> dict[str, Any]:
        from persona_dock.hermes_deployment import plan_hermes_deployment

        adapter = self if not container or container == self.container else HermesAdapter(container=container)
        return plan_hermes_deployment(
            package,
            profile=destination,
            profile_explicit=destination is not None,
            adapter=adapter,
        ).to_dict()
