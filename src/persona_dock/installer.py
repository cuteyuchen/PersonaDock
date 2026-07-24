from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .packaging import extract_package, inspect_package

STATE_ROOT = Path.home() / ".personadock"
STATE_FILE = STATE_ROOT / "state.json"
BACKUP_ROOT = STATE_ROOT / "backups"
Destination = str | Path
ResolvedDestination = Path | PurePosixPath


def default_target(target: str) -> Path:
    if target == "hermes":
        return Path.home() / ".hermes"
    if target == "openclaw":
        return Path.home() / ".openclaw" / "workspace"
    if target == "generic":
        return STATE_ROOT / "agents" / "generic"
    raise ValueError(f"unsupported target: {target}")


def _run_docker(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["docker", *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError("docker command was not found; install Docker or use a host-mounted --path") from error

    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"docker {' '.join(arguments)} failed: {detail}")
    return result


def _ensure_container(container: str) -> None:
    if not container.strip():
        raise ValueError("container name must not be empty")
    result = _run_docker(
        ["inspect", "--type", "container", "--format", "{{.State.Running}}", container]
    )
    if result.stdout.strip().lower() != "true":
        raise ValueError(f"Docker container is not running: {container}")


def _docker_exec(
    container: str,
    script: str,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run_docker(
        ["exec", container, "sh", "-c", script, "personadock", *arguments],
        check=check,
    )


def _container_home(container: str) -> PurePosixPath:
    result = _docker_exec(container, 'printf "%s" "${HOME:-}"')
    value = result.stdout.strip()
    if not value:
        raise ValueError("container HOME is empty; provide an absolute --path")
    home = PurePosixPath(value)
    if not home.is_absolute():
        raise ValueError(f"container HOME is not absolute: {value}")
    return home


def _container_target(target: str, container: str, destination: Destination | None) -> PurePosixPath:
    home: PurePosixPath | None = None
    if destination is None:
        home = _container_home(container)
        if target == "hermes":
            resolved = home / ".hermes"
        elif target == "openclaw":
            resolved = home / ".openclaw" / "workspace"
        elif target == "generic":
            resolved = home / ".personadock" / "agents" / "generic"
        else:
            raise ValueError(f"unsupported target: {target}")
    else:
        value = str(destination).strip().replace("\\", "/")
        if value == "~" or value.startswith("~/"):
            home = _container_home(container)
            value = str(home) if value == "~" else str(home / value[2:])
        resolved = PurePosixPath(value)

    if not resolved.is_absolute():
        raise ValueError("Docker destination must be an absolute container path")
    return resolved


def _docker_exists(container: str, path: PurePosixPath) -> bool:
    result = _docker_exec(container, 'test -e "$1"', str(path), check=False)
    if result.returncode not in {0, 1}:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"could not inspect {container}:{path}: {detail}")
    return result.returncode == 0


def _docker_remove(container: str, path: PurePosixPath) -> None:
    _docker_exec(container, 'rm -rf -- "$1"', str(path))


def _docker_mkdir(container: str, path: PurePosixPath) -> None:
    _docker_exec(container, 'mkdir -p -- "$1"', str(path))


def _docker_copy_from(container: str, source: PurePosixPath, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run_docker(["cp", f"{container}:{source}", str(destination)])


def _docker_copy_to(container: str, source: Path, destination: PurePosixPath) -> None:
    _docker_mkdir(container, destination.parent)
    _run_docker(["cp", str(source), f"{container}:{destination}"])


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.is_file():
        return {"installations": {}}
    value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid PersonaDock state")
    value.setdefault("installations", {})
    return value


def _save_state(state: dict[str, Any]) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _copy_with_backup(source: Path, destination: Path, backup_root: Path, managed: list[str], backups: dict[str, str]) -> None:
    relative_key = destination.as_posix()
    if destination.exists():
        backup = backup_root / f"{len(backups):04d}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_dir():
            shutil.copytree(destination, backup)
        else:
            shutil.copy2(destination, backup)
        backups[relative_key] = str(backup)
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    managed.append(relative_key)


def _copy_with_backup_docker(
    source: Path,
    destination: PurePosixPath,
    container: str,
    backup_root: Path,
    managed: list[str],
    backups: dict[str, str],
) -> None:
    destination_key = str(destination)
    if _docker_exists(container, destination):
        backup = backup_root / f"{len(backups):04d}"
        _docker_copy_from(container, destination, backup)
        backups[destination_key] = str(backup)
        _docker_remove(container, destination)
    _docker_copy_to(container, source, destination)
    managed.append(destination_key)


def _installation_key(target: str, destination: ResolvedDestination, container: str | None) -> str:
    if container:
        return f"{target}:docker:{container}:{destination}"
    return f"{target}:{destination}"


def install_package(
    package: Path,
    target: str,
    destination: Destination | None = None,
    container: str | None = None,
) -> ResolvedDestination:
    info = inspect_package(package)
    if info["integrity"] != "ok":
        raise ValueError("PersonaPack integrity check failed")
    if target not in info.get("targets", {}):
        raise ValueError(f"package does not contain target {target}")

    if container:
        _ensure_container(container)
        resolved_destination: ResolvedDestination = _container_target(target, container, destination)
        transport = "docker"
    else:
        resolved_destination = Path(destination or default_target(target)).expanduser().resolve()
        transport = "local"

    key = _installation_key(target, resolved_destination, container)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = BACKUP_ROOT / info["id"] / timestamp
    managed: list[str] = []
    backups: dict[str, str] = {}

    with tempfile.TemporaryDirectory(prefix="personadock-") as temporary:
        extracted = Path(temporary)
        extract_package(package, extracted)
        source = extracted / "targets" / target
        skill_id = next((p.name for p in (source / "skills").iterdir()), None) if (source / "skills").is_dir() else None

        if target in {"hermes", "openclaw"}:
            items: list[tuple[Path, str]] = [(source / "SOUL.md", "SOUL.md")]
            if skill_id:
                items.append((source / "skills" / skill_id, f"skills/{skill_id}"))
            if (source / "memory").is_dir():
                items.append((source / "memory", f"memory/personadock-{info['id']}"))
        else:
            items = [(source, info["id"])]

        for source_item, relative_destination in items:
            if container:
                assert isinstance(resolved_destination, PurePosixPath)
                _copy_with_backup_docker(
                    source_item,
                    resolved_destination / relative_destination,
                    container,
                    backup_root,
                    managed,
                    backups,
                )
            else:
                assert isinstance(resolved_destination, Path)
                _copy_with_backup(
                    source_item,
                    resolved_destination / relative_destination,
                    backup_root,
                    managed,
                    backups,
                )

    state = _load_state()
    state["installations"][key] = {
        "id": info["id"],
        "name": info["name"],
        "version": info["version"],
        "target": target,
        "transport": transport,
        "container": container,
        "destination": str(resolved_destination),
        "package": str(package.expanduser().resolve()),
        "installed_at": timestamp,
        "managed": managed,
        "backups": backups,
    }
    _save_state(state)
    return resolved_destination


def _resolve_destination(
    target: str,
    destination: Destination | None,
    container: str | None,
) -> ResolvedDestination:
    if container:
        _ensure_container(container)
        return _container_target(target, container, destination)
    return Path(destination or default_target(target)).expanduser().resolve()


def _find_record(
    target: str,
    destination: Destination | None = None,
    container: str | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any], ResolvedDestination]:
    resolved_destination = _resolve_destination(target, destination, container)
    key = _installation_key(target, resolved_destination, container)
    state = _load_state()
    record = state.get("installations", {}).get(key)
    if not record:
        location = f"{container}:{resolved_destination}" if container else str(resolved_destination)
        raise ValueError(f"no PersonaDock installation found at {location}")
    return key, state, record, resolved_destination


def rollback(
    target: str,
    destination: Destination | None = None,
    container: str | None = None,
) -> ResolvedDestination:
    key, state, record, resolved_destination = _find_record(target, destination, container)
    if container:
        for managed_path in record.get("managed", []):
            _docker_remove(container, PurePosixPath(managed_path))
        for destination_path, backup_path in record.get("backups", {}).items():
            source = Path(backup_path)
            if source.exists():
                _docker_copy_to(container, source, PurePosixPath(destination_path))
    else:
        for managed_path in record.get("managed", []):
            path = Path(managed_path)
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        for destination_path, backup_path in record.get("backups", {}).items():
            source = Path(backup_path)
            destination_path_obj = Path(destination_path)
            destination_path_obj.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination_path_obj)
            elif source.exists():
                shutil.copy2(source, destination_path_obj)
    state["installations"].pop(key, None)
    _save_state(state)
    return resolved_destination


def uninstall(
    target: str,
    destination: Destination | None = None,
    restore_previous: bool = True,
    container: str | None = None,
) -> ResolvedDestination:
    if restore_previous:
        return rollback(target, destination, container)
    key, state, record, resolved_destination = _find_record(target, destination, container)
    if container:
        for managed_path in record.get("managed", []):
            _docker_remove(container, PurePosixPath(managed_path))
    else:
        for managed_path in record.get("managed", []):
            path = Path(managed_path)
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
    state["installations"].pop(key, None)
    _save_state(state)
    return resolved_destination


def status() -> list[dict[str, Any]]:
    return list(_load_state().get("installations", {}).values())
