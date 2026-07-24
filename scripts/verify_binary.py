from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import subprocess
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any


def _run(
    binary: Path,
    cwd: Path,
    environment: dict[str, str],
    arguments: list[str],
    *,
    json_output: bool = False,
    timeout: int = 180,
) -> str | dict[str, Any] | list[Any]:
    command = [str(binary), *arguments]
    result = subprocess.run(
        command,
        check=False,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Standalone command failed\n"
            f"command: {command!r}\n"
            f"exit: {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    if not json_output:
        return result.stdout
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Standalone command returned invalid JSON\n"
            f"command: {command!r}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        ) from error


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _http_get(port: int, path: str) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _stop_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _verify_page(port: int, path: str, marker: str) -> None:
    status, body = _http_get(port, path)
    if status != 200:
        raise AssertionError(f"unexpected status for {path}: {status}")
    if marker not in body.decode("utf-8"):
        raise AssertionError(f"embedded Web marker missing for {path}: {marker}")


def _verify_web(binary: Path, environment: dict[str, str]) -> None:
    port = _free_port()
    process = subprocess.Popen(
        [
            str(binary),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-browser",
        ],
        cwd=binary.parent,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    failure: BaseException | None = None
    try:
        deadline = time.monotonic() + 30
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(
                    f"Web process exited before ready ({process.returncode}):\n{output}"
                )
            try:
                status, body = _http_get(port, "/api/health")
                if status != 200:
                    raise AssertionError(f"unexpected health status: {status}")
                health = json.loads(body.decode("utf-8"))
                if health.get("phase", 0) < 8:
                    raise AssertionError(health)
                required_true = (
                    "hermes_native_adapter",
                    "openclaw_native_adapter",
                    "workspace_state_separation",
                    "governed_memory_sync",
                    "reviewed_session_summaries",
                    "stable_1_0_contract",
                )
                if any(health.get(field) is not True for field in required_true):
                    raise AssertionError(health)
                if health.get("raw_session_sync") is not False:
                    raise AssertionError(health)
                if health.get("adapter_api_version") != "1.0":
                    raise AssertionError(health)
                if health.get("persona_pack_signatures") != "detached-ed25519-v1":
                    raise AssertionError(health)
                if health.get("encrypted_private_backup") != "aes-256-gcm-scrypt-v1":
                    raise AssertionError(health)
                for path, marker in (
                    ("/", "PersonaDock Control Plane"),
                    ("/canonical", "Canonical Persona"),
                    ("/hermes", "Hermes 原生 Profile 管理"),
                    ("/openclaw", "OpenClaw 原生 Agent 管理"),
                    ("/sync", "同步策略与审核中心"),
                    ("/sessions", "Session Summary 审核中心"),
                ):
                    _verify_page(port, path, marker)
                return
            except BaseException as error:
                last_error = error
                time.sleep(0.5)
        raise RuntimeError(f"Web control plane did not become ready: {last_error}")
    except BaseException as error:
        failure = error
        raise
    finally:
        _stop_process_tree(process)
        if failure is not None and process.stdout:
            output = process.stdout.read()
            if output:
                print("Web control plane output:\n" + output)


def _check_help(
    binary: Path,
    runtime_root: Path,
    environment: dict[str, str],
    command: str,
    markers: tuple[str, ...],
) -> None:
    arguments = ["--help"] if not command else [command, "--help"]
    output = str(_run(binary, runtime_root, environment, arguments))
    for marker in markers:
        if marker not in output:
            raise AssertionError(f"{command or 'main'} help is missing: {marker}")


def _verify_1_0_workflow(
    binary: Path,
    runtime_root: Path,
    environment: dict[str, str],
) -> None:
    project = runtime_root / "golden-persona"
    package = runtime_root / "golden.personapack"
    private_key = runtime_root / "signing.pem"
    signature = runtime_root / "golden.personapack.sig.json"
    backup = runtime_root / "golden.pdbackup"
    restored = runtime_root / "restored"
    card = runtime_root / "golden-card.json"

    _run(binary, runtime_root, environment, ["init", str(project), "--id", "golden", "--name", "Golden"])
    _run(binary, runtime_root, environment, ["pack", str(project), "--output", str(package)])
    package_info = _run(
        binary,
        runtime_root,
        environment,
        ["inspect", str(package)],
        json_output=True,
    )
    assert isinstance(package_info, dict)
    if package_info.get("integrity") != "ok":
        raise AssertionError(package_info)
    if package_info.get("compatibility", {}).get("adapter_api") != "1.x":
        raise AssertionError(package_info)

    key_info = _run(
        binary,
        runtime_root,
        environment,
        ["trust", "keygen", str(private_key), "--json"],
        json_output=True,
    )
    assert isinstance(key_info, dict)
    public_key = Path(str(key_info["public_key"]))
    _run(
        binary,
        runtime_root,
        environment,
        ["trust", "sign", str(package), "--key", str(private_key), "--output", str(signature), "--json"],
        json_output=True,
    )
    verified = _run(
        binary,
        runtime_root,
        environment,
        ["trust", "verify", str(package), "--signature", str(signature), "--trusted-key", str(public_key), "--json"],
        json_output=True,
    )
    assert isinstance(verified, dict)
    if verified.get("signature") != "valid-trusted" or verified.get("trusted") is not True:
        raise AssertionError(verified)

    backup_info = _run(
        binary,
        runtime_root,
        environment,
        ["backup", "create", str(project), "--output", str(backup), "--json"],
        json_output=True,
    )
    assert isinstance(backup_info, dict)
    if backup_info.get("algorithm") != "AES-256-GCM":
        raise AssertionError(backup_info)
    _run(
        binary,
        runtime_root,
        environment,
        ["backup", "restore", str(backup), str(restored), "--json"],
        json_output=True,
    )
    if not (restored / "companion.yaml").is_file():
        raise AssertionError("private backup restore did not recreate companion.yaml")

    _run(
        binary,
        runtime_root,
        environment,
        ["character-card", "export", str(project), "--output", str(card), "--card-version", "3", "--json"],
        json_output=True,
    )
    card_info = _run(
        binary,
        runtime_root,
        environment,
        ["character-card", "inspect", str(card), "--json"],
        json_output=True,
    )
    assert isinstance(card_info, dict)
    if card_info.get("spec") != "chara_card_v3":
        raise AssertionError(card_info)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a PersonaDock standalone executable.")
    parser.add_argument("--binary", required=True, type=Path)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    if not binary.is_file():
        raise FileNotFoundError(binary)

    with tempfile.TemporaryDirectory(prefix="personadock-runtime-") as directory:
        runtime_root = Path(directory)
        environment = dict(os.environ)
        environment["PERSONADOCK_HOME"] = str(runtime_root / "state")
        environment["PERSONADOCK_BACKUP_PASSWORD"] = "standalone-test-password"
        version = str(_run(binary, runtime_root, environment, ["--version"]))
        if "1.0.0" not in version:
            raise AssertionError(version)

        _check_help(
            binary,
            runtime_root,
            environment,
            "",
            ("hermes", "openclaw", "sync", "session", "adapter", "trust", "backup", "character-card"),
        )
        help_contracts = {
            "hermes": ("doctor", "profiles", "rollback", "memory"),
            "openclaw": ("doctor", "agents", "rollback", "memory"),
            "sync": ("policy", "collect", "candidates", "review", "plan", "apply"),
            "session": ("policy", "collect", "list", "review", "preview"),
            "adapter": ("list", "show", "doctor"),
            "trust": ("keygen", "sign", "verify"),
            "backup": ("create", "inspect", "restore"),
            "character-card": ("inspect", "import", "export"),
        }
        for command, markers in help_contracts.items():
            _check_help(binary, runtime_root, environment, command, markers)

        adapters = _run(
            binary,
            runtime_root,
            environment,
            ["adapter", "list", "--no-plugins", "--json"],
            json_output=True,
        )
        assert isinstance(adapters, dict)
        if adapters.get("adapter_api_version") != "1.0":
            raise AssertionError(adapters)

        skill_root = runtime_root / "installed-skills"
        _run(
            binary,
            runtime_root,
            environment,
            ["skill", "install", "--target", "generic", "--scope", "project", "--path", str(skill_root)],
        )
        for relative in (
            "persona-builder/SKILL.md",
            "persona-builder/references/output-contract.md",
            "persona-builder/references/prompt-contract.md",
            "persona-builder/references/evidence-contract.md",
            "persona-builder/references/memory-contract.md",
        ):
            if not (skill_root / relative).is_file():
                raise FileNotFoundError(skill_root / relative)

        _verify_1_0_workflow(binary, runtime_root, environment)
        _verify_web(binary, environment)

    print(f"Verified PersonaDock 1.0 standalone binary: {binary}")
    return 0


def _persist_failure() -> None:
    diagnostics = Path("build/personadock/warn-personadock.txt")
    diagnostics.parent.mkdir(parents=True, exist_ok=True)
    with diagnostics.open("a", encoding="utf-8") as stream:
        stream.write("\n\n=== PersonaDock standalone verification failure ===\n")
        stream.write(traceback.format_exc())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:
        _persist_failure()
        raise
