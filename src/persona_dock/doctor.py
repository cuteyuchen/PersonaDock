from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from typing import Any, Callable

from persona_dock import __version__
from persona_dock.adapters.base import AdapterDoctorResult
from persona_dock.adapters.hermes import (
    HermesAdapter,
    version_from_text as hermes_version_from_text,
)
from persona_dock.adapters.legacy_filesystem import LegacyFilesystemAdapter
from persona_dock.adapters.openclaw import (
    OpenClawAdapter,
    version_from_text as openclaw_version_from_text,
)

_DOCKER_PROBE_TIMEOUT = 5
_DOCKER_SCAN_WORKERS = 8


def _run_command(
    command: list[str],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _docker_executable() -> str | None:
    return shutil.which("docker")


def _container_name(payload: dict[str, Any]) -> str | None:
    names = payload.get("Names") or payload.get("names") or payload.get("Name") or payload.get("name")
    if isinstance(names, list):
        for item in names:
            value = str(item).lstrip("/").strip()
            if value:
                return value
        return None
    if not isinstance(names, str):
        return None
    for part in names.replace(",", " ").split():
        value = part.lstrip("/").strip()
        if value:
            return value
    return None


def _container_image(payload: dict[str, Any]) -> str | None:
    image = payload.get("Image") or payload.get("image")
    if image is None:
        return None
    value = str(image).strip()
    return value or None


def _list_running_docker_containers(
    *,
    docker_executable: str | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    docker = docker_executable or _docker_executable()
    if not docker:
        return [], {
            "status": "unavailable",
            "reason": "docker-cli-missing",
            "message": "Docker CLI is not available on PATH",
            "container_count": 0,
        }

    try:
        completed = _run_command(
            [docker, "ps", "--format", "{{json .}}"],
            timeout=15,
        )
    except FileNotFoundError:
        return [], {
            "status": "unavailable",
            "reason": "docker-cli-missing",
            "message": "Docker CLI is not available on PATH",
            "container_count": 0,
        }
    except OSError as error:
        return [], {
            "status": "unavailable",
            "reason": "docker-os-error",
            "message": str(error),
            "container_count": 0,
        }
    except subprocess.TimeoutExpired:
        return [], {
            "status": "unavailable",
            "reason": "docker-timeout",
            "message": "docker ps timed out",
            "container_count": 0,
        }

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        return [], {
            "status": "unavailable",
            "reason": "docker-daemon-unavailable",
            "message": detail,
            "container_count": 0,
        }

    containers: list[dict[str, str]] = []
    for raw in completed.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        name = _container_name(payload)
        if not name:
            continue
        image = _container_image(payload) or ""
        containers.append({"name": name, "image": image})

    containers.sort(key=lambda item: item["name"].lower())
    return containers, {
        "status": "ok",
        "reason": "scanned",
        "message": f"scanned {len(containers)} running container(s)",
        "container_count": len(containers),
    }


def _probe_container_cli(
    *,
    docker_executable: str,
    container: str,
    cli: str,
    arguments: list[str],
) -> dict[str, Any]:
    command = [docker_executable, "exec", container, cli, *arguments]
    try:
        completed = _run_command(command, timeout=_DOCKER_PROBE_TIMEOUT)
    except FileNotFoundError as error:
        return {
            "present": False,
            "container": container,
            "error": str(error),
            "version": None,
        }
    except OSError as error:
        return {
            "present": False,
            "container": container,
            "error": str(error),
            "version": None,
        }
    except subprocess.TimeoutExpired:
        return {
            "present": False,
            "container": container,
            "error": f"{cli} probe timed out after {_DOCKER_PROBE_TIMEOUT}s",
            "version": None,
        }

    if completed.returncode != 0:
        return {
            "present": False,
            "container": container,
            "error": completed.stderr.strip()
            or completed.stdout.strip()
            or f"exit {completed.returncode}",
            "version": None,
        }

    text = "\n".join((completed.stdout, completed.stderr))
    if cli == "hermes":
        version = hermes_version_from_text(text)
    else:
        version = openclaw_version_from_text(text)
    return {
        "present": True,
        "container": container,
        "error": None,
        "version": version,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _probe_containers_for_cli(
    containers: list[dict[str, str]],
    *,
    docker_executable: str,
    cli: str,
    arguments: list[str],
) -> list[dict[str, Any]]:
    if not containers:
        return []

    hits: list[dict[str, Any]] = []
    workers = min(_DOCKER_SCAN_WORKERS, len(containers))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _probe_container_cli,
                docker_executable=docker_executable,
                container=item["name"],
                cli=cli,
                arguments=arguments,
            ): item
            for item in containers
        }
        for future in as_completed(futures):
            container = futures[future]
            try:
                result = future.result()
            except Exception as error:  # pragma: no cover - defensive
                result = {
                    "present": False,
                    "container": container["name"],
                    "error": str(error),
                    "version": None,
                }
            if not result.get("present"):
                continue
            hits.append(
                {
                    "name": container["name"],
                    "image": container.get("image") or "",
                    "version": result.get("version"),
                }
            )
    hits.sort(key=lambda item: item["name"].lower())
    return hits


def _candidate_summary(result: AdapterDoctorResult, *, image: str | None = None) -> dict[str, Any]:
    details = dict(result.details or {})
    value = {
        "container": details.get("container") or result.details.get("container"),
        "image": image or details.get("image"),
        "version": result.version,
        "status": result.status,
        "available": result.available,
        "message": result.message,
        "executable": result.executable,
    }
    return value


def _with_docker_metadata(
    result: AdapterDoctorResult,
    *,
    discovery_source: str,
    docker_scan: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    image: str | None = None,
) -> AdapterDoctorResult:
    details = dict(result.details or {})
    details["transport"] = (
        "docker" if details.get("container") else details.get("transport", "local")
    )
    details["discovery_source"] = discovery_source
    details["docker_scan"] = docker_scan
    if candidates is not None:
        details["candidates"] = candidates
    if image is not None:
        details["image"] = image
    return replace(result, details=details)


def _attach_local_scan(
    result: AdapterDoctorResult,
    *,
    docker_scan: dict[str, Any] | None = None,
) -> AdapterDoctorResult:
    details = dict(result.details or {})
    details.setdefault("transport", "local" if not details.get("container") else "docker")
    details.setdefault("discovery_source", "local")
    if docker_scan is not None:
        details["docker_scan"] = docker_scan
    return replace(result, details=details)


def _resolve_docker_adapter(
    *,
    adapter_name: str,
    local_result: AdapterDoctorResult,
    containers: list[dict[str, str]],
    docker_scan: dict[str, Any],
    docker_executable: str | None,
    cli: str,
    arguments: list[str],
    factory: Callable[[str], Any],
) -> AdapterDoctorResult:
    if local_result.status != "unavailable":
        return _attach_local_scan(local_result)

    if docker_scan.get("status") != "ok" or not docker_executable:
        return _attach_local_scan(local_result, docker_scan=docker_scan)

    if not containers:
        scan = {
            **docker_scan,
            "reason": "no-running-containers",
            "message": "no running Docker containers were found",
        }
        return _attach_local_scan(local_result, docker_scan=scan)

    hits = _probe_containers_for_cli(
        containers,
        docker_executable=docker_executable,
        cli=cli,
        arguments=arguments,
    )
    if not hits:
        scan = {
            **docker_scan,
            "reason": f"no-{adapter_name}-containers",
            "message": f"no running containers exposed a working {cli} CLI",
            "matched_count": 0,
        }
        return _attach_local_scan(local_result, docker_scan=scan)

    evaluated: list[tuple[dict[str, Any], AdapterDoctorResult]] = []
    for hit in hits:
        doctor_result = factory(hit["name"]).doctor()
        evaluated.append((hit, doctor_result))

    candidates = [
        _candidate_summary(result, image=hit.get("image"))
        for hit, result in evaluated
    ]
    scan = {
        **docker_scan,
        "matched_count": len(evaluated),
        "reason": "docker-auto",
        "message": f"discovered {len(evaluated)} {adapter_name} container candidate(s)",
    }

    if len(evaluated) > 1:
        names = ", ".join(hit["name"] for hit, _ in evaluated)
        ready_count = sum(1 for _, result in evaluated if result.available and result.status == "ready")
        return AdapterDoctorResult(
            adapter=adapter_name,
            available=False,
            executable=None,
            version=None,
            status="ambiguous",
            message=(
                f"Multiple Docker containers expose {adapter_name}: {names}. "
                f"Use `personadock {adapter_name} doctor --container <name> --json` "
                "to inspect one explicitly."
                + (f" Ready candidates: {ready_count}." if ready_count else "")
            ),
            capabilities=local_result.capabilities,
            details={
                "native": True,
                "transport": "docker",
                "container": None,
                "discovery_source": "docker-auto",
                "docker_scan": scan,
                "candidates": candidates,
            },
        )

    hit, result = evaluated[0]
    if result.available and result.status == "ready":
        enriched = _with_docker_metadata(
            result,
            discovery_source="docker-auto",
            docker_scan=scan,
            candidates=candidates,
            image=hit.get("image"),
        )
        return replace(
            enriched,
            message=(
                f"{result.message.rstrip('.')} via Docker container {hit['name']}."
            ),
        )

    degraded_status = result.status if result.status in {"degraded", "unavailable"} else "degraded"
    enriched = _with_docker_metadata(
        result,
        discovery_source="docker-auto",
        docker_scan=scan,
        candidates=candidates,
        image=hit.get("image"),
    )
    return replace(
        enriched,
        available=False,
        status=degraded_status if degraded_status != "unavailable" else "degraded",
        message=(
            f"{adapter_name} was found in Docker container {hit['name']} but is not fully ready: "
            f"{result.message}"
        ),
    )


def doctor_report() -> dict[str, Any]:
    hermes_local = HermesAdapter().doctor()
    openclaw_local = OpenClawAdapter().doctor()
    generic = LegacyFilesystemAdapter("generic").doctor()

    need_docker = any(
        result.status == "unavailable"
        for result in (hermes_local, openclaw_local)
    )

    containers: list[dict[str, str]] = []
    docker_scan: dict[str, Any] = {
        "status": "skipped",
        "reason": "local-ready",
        "message": "local Hermes and OpenClaw CLIs are ready",
        "container_count": 0,
    }
    docker = None
    if need_docker:
        docker = _docker_executable()
        containers, docker_scan = _list_running_docker_containers(
            docker_executable=docker
        )

    hermes = _resolve_docker_adapter(
        adapter_name="hermes",
        local_result=hermes_local,
        containers=containers,
        docker_scan=docker_scan,
        docker_executable=docker,
        cli="hermes",
        arguments=["version"],
        factory=lambda name: HermesAdapter(container=name, docker_executable=docker),
    )
    openclaw = _resolve_docker_adapter(
        adapter_name="openclaw",
        local_result=openclaw_local,
        containers=containers,
        docker_scan=docker_scan,
        docker_executable=docker,
        cli="openclaw",
        arguments=["--version"],
        factory=lambda name: OpenClawAdapter(container=name, docker_executable=docker),
    )

    return {
        "personadock_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "executable": sys.executable,
        "web": {
            "default_host": "127.0.0.1",
            "default_port": 8732,
            "remote_requires_token": True,
        },
        "adapters": [result.to_dict() for result in (hermes, openclaw, generic)],
    }


def render_doctor(report: dict[str, Any]) -> str:
    lines = [
        f"PersonaDock {report['personadock_version']}",
        f"Platform: {report['platform']} ({report['machine']})",
        f"Python: {report['python_version']}",
        "",
        "Adapters:",
    ]
    for adapter in report["adapters"]:
        lines.append(f"- {adapter['adapter']}: {adapter['status']}")
        lines.append(f"  {adapter['message']}")
        if adapter.get("executable"):
            lines.append(f"  executable: {adapter['executable']}")
        if adapter.get("version"):
            lines.append(f"  version: {adapter['version']}")
        details = adapter.get("details", {}) or {}
        transport = details.get("transport")
        if transport:
            lines.append(f"  transport: {transport}")
        container = details.get("container")
        if container:
            lines.append(f"  container: {container}")
        target_path = details.get("target_path")
        if target_path:
            lines.append(f"  target: {target_path}")
        candidates = details.get("candidates") or []
        if adapter.get("status") == "ambiguous" and candidates:
            lines.append("  candidates:")
            for item in candidates:
                label = item.get("container") or "unknown"
                version = item.get("version") or "unknown"
                status = item.get("status") or "unknown"
                lines.append(f"  - {label} ({status}, version {version})")
            lines.append(
                f"  next: personadock {adapter['adapter']} doctor --container <name> --json"
            )
        docker_scan = details.get("docker_scan")
        if docker_scan and adapter.get("status") in {"unavailable", "degraded", "ambiguous"}:
            reason = docker_scan.get("reason")
            if reason and reason not in {"local-ready", "scanned"}:
                lines.append(f"  docker_scan: {reason}")
        if details.get("native"):
            if adapter["adapter"] == "hermes":
                lines.append("  deployment: native Hermes Profile Distribution")
            elif adapter["adapter"] == "openclaw":
                lines.append("  deployment: native OpenClaw Agent/Workspace overlay")
                lines.append("  safety: workspace and agent state directory remain separate")
    return "\n".join(lines)
