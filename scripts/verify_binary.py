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
    page = body.decode("utf-8")
    if marker not in page:
        raise AssertionError(f"embedded Web page marker is missing for {path}: {marker}")


def _verify_web(binary: Path) -> None:
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    failure: Exception | None = None
    try:
        deadline = time.monotonic() + 30
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(
                    f"Web control plane exited before becoming ready ({process.returncode}):\n{output}"
                )
            try:
                health_status, health_body = _http_get(port, "/api/health")
                if health_status != 200:
                    raise AssertionError(f"unexpected health status: {health_status}")
                health = json.loads(health_body.decode("utf-8"))
                if health.get("status") != "ok":
                    raise AssertionError(f"unexpected health response: {health}")
                if health.get("phase", 0) < 6:
                    raise AssertionError(f"standalone Web health is not Phase 6: {health}")
                for marker in (
                    "hermes_native_adapter",
                    "openclaw_native_adapter",
                    "workspace_state_separation",
                    "governed_memory_sync",
                ):
                    if health.get(marker) is not True:
                        raise AssertionError(f"health flag is missing: {marker}: {health}")
                if health.get("raw_session_sync") is not False:
                    raise AssertionError(f"raw session sync safety flag is invalid: {health}")

                _verify_page(port, "/", "PersonaDock Control Plane")
                _verify_page(port, "/canonical", "Canonical Persona")
                _verify_page(port, "/hermes", "Hermes 原生 Profile 管理")
                _verify_page(port, "/openclaw", "OpenClaw 原生 Agent 管理")
                _verify_page(port, "/sync", "同步策略与审核中心")
                return
            except Exception as error:
                last_error = error
                time.sleep(0.5)
        raise RuntimeError(f"Web control plane did not become ready: {last_error}")
    except Exception as error:
        failure = error
        raise
    finally:
        _stop_process_tree(process)
        if failure is not None and process.stdout:
            output = process.stdout.read()
            if output:
                print("Web control plane output:\n" + output)


def _run_help(binary: Path, runtime_root: Path, arguments: list[str]) -> str:
    result = subprocess.run(
        [str(binary), *arguments],
        check=True,
        cwd=runtime_root,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a PersonaDock standalone executable.")
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()

    binary = args.binary.resolve()
    if not binary.is_file():
        raise FileNotFoundError(binary)

    with tempfile.TemporaryDirectory(prefix="personadock-runtime-") as runtime_dir:
        runtime_root = Path(runtime_dir)
        skill_root = runtime_root / "installed-skills"

        main_help = _run_help(binary, runtime_root, ["--help"])
        for marker in ("hermes", "openclaw", "sync"):
            if marker not in main_help:
                raise AssertionError(f"standalone CLI does not expose command: {marker}")

        hermes_help = _run_help(binary, runtime_root, ["hermes", "--help"])
        for marker in ("doctor", "profiles", "rollback", "memory"):
            if marker not in hermes_help:
                raise AssertionError(f"standalone Hermes CLI marker is missing: {marker}")

        openclaw_help = _run_help(binary, runtime_root, ["openclaw", "--help"])
        for marker in ("doctor", "agents", "rollback", "memory"):
            if marker not in openclaw_help:
                raise AssertionError(f"standalone OpenClaw CLI marker is missing: {marker}")

        sync_help = _run_help(binary, runtime_root, ["sync", "--help"])
        for marker in ("policy", "collect", "candidates", "review", "conflicts", "plan", "apply", "status"):
            if marker not in sync_help:
                raise AssertionError(f"standalone sync CLI marker is missing: {marker}")

        deploy_help = _run_help(binary, runtime_root, ["deploy", "--help"])
        for marker in (
            "--profile",
            "--activate",
            "--agent",
            "--workspace",
            "--take-ownership",
            "--ssh-host",
            "--legacy-filesystem",
        ):
            if marker not in deploy_help:
                raise AssertionError(f"standalone deploy marker is missing: {marker}")

        doctor = subprocess.run(
            [str(binary), "doctor", "--json"],
            check=True,
            cwd=runtime_root,
            capture_output=True,
            text=True,
        )
        doctor_data = json.loads(doctor.stdout)
        if "adapters" not in doctor_data:
            raise AssertionError("standalone doctor output does not contain adapters")
        for adapter_name in ("hermes", "openclaw"):
            adapter = next(
                (
                    item
                    for item in doctor_data["adapters"]
                    if item.get("adapter") == adapter_name
                ),
                None,
            )
            if (
                adapter is None
                or adapter.get("capabilities", {}).get("native_deployment") is not True
            ):
                raise AssertionError(
                    f"standalone doctor does not expose native {adapter_name} capability"
                )
        openclaw = next(
            item
            for item in doctor_data["adapters"]
            if item.get("adapter") == "openclaw"
        )
        if openclaw.get("details", {}).get("workspace_state_separation") is not True:
            raise AssertionError("OpenClaw doctor does not expose workspace/state separation")

        subprocess.run(
            [
                str(binary),
                "skill",
                "install",
                "--target",
                "generic",
                "--scope",
                "project",
                "--path",
                str(skill_root),
            ],
            check=True,
            cwd=runtime_root,
        )

        required = [
            "persona-builder/SKILL.md",
            "persona-builder/references/output-contract.md",
            "persona-builder/references/prompt-contract.md",
            "persona-builder/references/evidence-contract.md",
            "persona-builder/references/memory-contract.md",
        ]
        for relative in required:
            path = skill_root / relative
            if not path.is_file():
                raise FileNotFoundError(path)

        skill_text = (skill_root / "persona-builder/SKILL.md").read_text(encoding="utf-8")
        for marker in ("Create mode", "Distill mode", "Hybrid mode", "Refine mode"):
            if marker not in skill_text:
                raise AssertionError(f"missing Skill marker: {marker}")

        _verify_web(binary)

    print(f"Verified standalone binary: {binary}")
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
