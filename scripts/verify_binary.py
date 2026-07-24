from __future__ import annotations

import argparse
import json
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _verify_web(binary: Path, runtime_root: Path) -> None:
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
        cwd=runtime_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = ""
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
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health",
                    timeout=1,
                ) as response:
                    health = json.loads(response.read().decode("utf-8"))
                if health.get("status") != "ok":
                    raise AssertionError(f"unexpected health response: {health}")
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/",
                    timeout=1,
                ) as response:
                    page = response.read().decode("utf-8")
                if "PersonaDock Control Plane" not in page:
                    raise AssertionError("embedded Web page marker is missing")
                return
            except Exception as error:  # startup polling deliberately accepts transient failures
                last_error = error
                time.sleep(0.5)
        raise RuntimeError(f"Web control plane did not become ready: {last_error}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


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

        subprocess.run([str(binary), "--help"], check=True, cwd=runtime_root)
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

        _verify_web(binary, runtime_root)

    print(f"Verified standalone binary: {binary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
