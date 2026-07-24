from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from persona_dock.adapters.base import (
    AdapterCapabilities,
    AdapterDoctorResult,
    PersonaAdapter,
)


class OpenClawAdapterError(RuntimeError):
    """Raised when an OpenClaw native operation cannot be completed safely."""


@dataclass(frozen=True)
class OpenClawCommandResult:
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
class OpenClawAgent:
    id: str
    name: str
    workspace: str
    agent_dir: str | None
    identity: dict[str, Any] = field(default_factory=dict)
    bindings: tuple[dict[str, Any], ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["bindings"] = list(self.bindings)
        return value


_VERSION = re.compile(r"(?<!\d)(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)")
_AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RESERVED_NEW_AGENT_IDS = {"main"}


def version_from_text(text: str) -> str | None:
    match = _VERSION.search(text)
    return match.group(1) if match else None


def validate_agent_id(agent_id: str, *, explicit_main: bool) -> None:
    if not _AGENT_ID.fullmatch(agent_id):
        raise OpenClawAdapterError(
            "OpenClaw agent ID must start with a letter or digit and contain only letters, digits, '.', '_' or '-'"
        )
    if agent_id == "main" and not explicit_main:
        raise OpenClawAdapterError(
            "PersonaDock will not target the reserved main OpenClaw agent implicitly; pass --agent main explicitly"
        )


def _agent_value(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value and value[key] is not None:
            return value[key]
    return None


def parse_agents_json(text: str) -> list[OpenClawAgent]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise OpenClawAdapterError(f"OpenClaw returned invalid agents JSON: {error}") from error
    if isinstance(payload, dict):
        values = next(
            (
                payload[key]
                for key in ("agents", "items", "data")
                if isinstance(payload.get(key), list)
            ),
            [payload] if any(key in payload for key in ("id", "agentId", "workspace")) else [],
        )
    elif isinstance(payload, list):
        values = payload
    else:
        values = []

    agents: list[OpenClawAgent] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        agent_id = str(_agent_value(raw, "id", "agentId", "agent_id") or "").strip()
        workspace = str(
            _agent_value(raw, "workspace", "workspacePath", "workspace_path") or ""
        ).strip()
        if not agent_id or not workspace:
            continue
        identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
        bindings_value = raw.get("bindings") if isinstance(raw.get("bindings"), list) else []
        agents.append(
            OpenClawAgent(
                id=agent_id,
                name=str(identity.get("name") or raw.get("name") or agent_id),
                workspace=workspace,
                agent_dir=(
                    str(_agent_value(raw, "agentDir", "agent_dir", "stateDir", "state_dir"))
                    if _agent_value(raw, "agentDir", "agent_dir", "stateDir", "state_dir")
                    else None
                ),
                identity=dict(identity),
                bindings=tuple(item for item in bindings_value if isinstance(item, dict)),
                raw=raw,
            )
        )
    return sorted(agents, key=lambda item: (item.id != "main", item.id.lower()))


def _quote(command: Iterable[str]) -> str:
    return " ".join(shlex.quote(value) for value in command)


class OpenClawCommandRunner:
    def __init__(
        self,
        *,
        executable: str | None = None,
        container: str | None = None,
        ssh_host: str | None = None,
        docker_executable: str | None = None,
        ssh_executable: str | None = None,
        scp_executable: str | None = None,
    ) -> None:
        if container and ssh_host:
            raise OpenClawAdapterError("choose either Docker or SSH transport, not both")
        self.container = container
        self.ssh_host = ssh_host
        self.executable = executable or shutil.which("openclaw") or "openclaw"
        self.docker_executable = docker_executable or shutil.which("docker") or "docker"
        self.ssh_executable = ssh_executable or shutil.which("ssh") or "ssh"
        self.scp_executable = scp_executable or shutil.which("scp") or "scp"

    @property
    def transport(self) -> str:
        if self.container:
            return "docker"
        if self.ssh_host:
            return "ssh"
        return "local"

    def command(self, arguments: Iterable[str]) -> list[str]:
        values = list(arguments)
        if self.container:
            return [self.docker_executable, "exec", self.container, "openclaw", *values]
        if self.ssh_host:
            return [self.ssh_executable, self.ssh_host, "openclaw", *values]
        return [self.executable, *values]

    def run(
        self,
        arguments: Iterable[str],
        *,
        timeout: int = 60,
        check: bool = False,
    ) -> OpenClawCommandResult:
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
            raise OpenClawAdapterError(f"failed to run {_quote(command)}: {error}") from error
        result = OpenClawCommandResult(
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and not result.ok:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise OpenClawAdapterError(f"{_quote(command)} failed: {detail}")
        return result

    def shell(self, script: str, *, timeout: int = 60, check: bool = False) -> OpenClawCommandResult:
        if self.container:
            command = [
                self.docker_executable,
                "exec",
                self.container,
                "sh",
                "-lc",
                script,
            ]
        elif self.ssh_host:
            command = [self.ssh_executable, self.ssh_host, "sh", "-lc", script]
        else:
            command = ["sh", "-lc", script]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
            raise OpenClawAdapterError(f"failed to run {_quote(command)}: {error}") from error
        result = OpenClawCommandResult(
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and not result.ok:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise OpenClawAdapterError(f"{_quote(command)} failed: {detail}")
        return result

    def copy_to(self, source: str | Path, destination: str) -> None:
        source_value = str(source)
        if self.container:
            command = [
                self.docker_executable,
                "cp",
                source_value,
                f"{self.container}:{destination}",
            ]
        elif self.ssh_host:
            command = [self.scp_executable, "-r", source_value, f"{self.ssh_host}:{destination}"]
        else:
            source_path = Path(source_value)
            destination_path = Path(destination).expanduser().resolve()
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            if source_path.is_dir():
                shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
            else:
                shutil.copy2(source_path, destination_path)
            return
        self._copy_command(command)

    def copy_from(self, source: str, destination: str | Path) -> None:
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if self.container:
            command = [
                self.docker_executable,
                "cp",
                f"{self.container}:{source}",
                str(destination_path),
            ]
        elif self.ssh_host:
            command = [self.scp_executable, "-r", f"{self.ssh_host}:{source}", str(destination_path)]
        else:
            source_path = Path(source).expanduser().resolve()
            if source_path.is_dir():
                shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
            elif source_path.is_file():
                shutil.copy2(source_path, destination_path)
            else:
                raise OpenClawAdapterError(f"source does not exist: {source_path}")
            return
        self._copy_command(command)

    @staticmethod
    def _copy_command(command: list[str]) -> None:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
            raise OpenClawAdapterError(f"failed to run {_quote(command)}: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "copy failed"
            raise OpenClawAdapterError(f"{_quote(command)} failed: {detail}")

    def read_text(self, path: str) -> str | None:
        if self.transport == "local":
            local = Path(path).expanduser().resolve()
            return local.read_text(encoding="utf-8", errors="replace") if local.is_file() else None
        result = self.shell(f"test -f {shlex.quote(path)} && cat {shlex.quote(path)}")
        return result.stdout if result.ok else None

    def write_text(self, path: str, content: str) -> None:
        if self.transport == "local":
            local = Path(path).expanduser().resolve()
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(content, encoding="utf-8")
            return
        with tempfile.TemporaryDirectory(prefix="personadock-openclaw-") as directory:
            local = Path(directory) / "payload"
            local.write_text(content, encoding="utf-8")
            parent = str(PurePosixPath(path).parent)
            self.shell(f"mkdir -p {shlex.quote(parent)}", check=True)
            self.copy_to(local, path)

    def exists(self, path: str) -> bool:
        if self.transport == "local":
            return Path(path).expanduser().resolve().exists()
        return self.shell(f"test -e {shlex.quote(path)}").ok

    def list_markdown(self, directory: str) -> list[str]:
        if self.transport == "local":
            root = Path(directory).expanduser().resolve()
            return [str(path) for path in sorted(root.glob("*.md")) if path.is_file()] if root.is_dir() else []
        result = self.shell(
            f"if test -d {shlex.quote(directory)}; then find {shlex.quote(directory)} -maxdepth 1 -type f -name '*.md' -print; fi"
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()] if result.ok else []


class OpenClawAdapter(PersonaAdapter):
    name = "openclaw"

    def __init__(
        self,
        *,
        executable: str | None = None,
        container: str | None = None,
        ssh_host: str | None = None,
        docker_executable: str | None = None,
        ssh_executable: str | None = None,
        scp_executable: str | None = None,
    ) -> None:
        self.runner = OpenClawCommandRunner(
            executable=executable,
            container=container,
            ssh_host=ssh_host,
            docker_executable=docker_executable,
            ssh_executable=ssh_executable,
            scp_executable=scp_executable,
        )
        self.container = container
        self.ssh_host = ssh_host

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
        executable = self.runner.executable
        if self.container:
            executable = "docker exec openclaw"
        elif self.ssh_host:
            executable = f"ssh {self.ssh_host} openclaw"
        details = {
            "native": True,
            "transport": self.runner.transport,
            "container": self.container,
            "ssh_host": self.ssh_host,
            "workspace_state_separation": True,
        }
        try:
            version_result = self.runner.run(["--version"], timeout=20)
        except OpenClawAdapterError as error:
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
        version = version_from_text(version_result.stdout + "\n" + version_result.stderr)
        if not version_result.ok:
            return AdapterDoctorResult(
                adapter=self.name,
                available=False,
                executable=executable,
                version=version,
                status="unavailable",
                message=version_result.stderr.strip() or version_result.stdout.strip() or "OpenClaw --version failed",
                capabilities=self.capabilities,
                details=details,
            )
        agents_result = self.runner.run(["agents", "list", "--json"], timeout=30)
        if not agents_result.ok:
            return AdapterDoctorResult(
                adapter=self.name,
                available=False,
                executable=executable,
                version=version,
                status="degraded",
                message=agents_result.stderr.strip() or agents_result.stdout.strip() or "OpenClaw agents list failed",
                capabilities=self.capabilities,
                details=details,
            )
        try:
            agents = parse_agents_json(agents_result.stdout)
        except OpenClawAdapterError as error:
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
        details["agent_count"] = len(agents)
        return AdapterDoctorResult(
            adapter=self.name,
            available=True,
            executable=executable,
            version=version,
            status="ready",
            message="OpenClaw CLI and native Agent/Workspace commands are available.",
            capabilities=self.capabilities,
            details=details,
        )

    def list_agents(self) -> list[OpenClawAgent]:
        result = self.runner.run(["agents", "list", "--json", "--bindings"], check=True, timeout=45)
        return parse_agents_json(result.stdout)

    def agent(self, agent_id: str) -> OpenClawAgent | None:
        return next((item for item in self.list_agents() if item.id == agent_id), None)

    def plan_deployment(
        self,
        package: str,
        *,
        destination: str | None = None,
        container: str | None = None,
    ) -> dict[str, Any]:
        from persona_dock.openclaw_deployment import plan_openclaw_deployment

        adapter = self
        if container and container != self.container:
            adapter = OpenClawAdapter(container=container)
        return plan_openclaw_deployment(
            package,
            agent=destination,
            agent_explicit=destination is not None,
            adapter=adapter,
        ).to_dict()
