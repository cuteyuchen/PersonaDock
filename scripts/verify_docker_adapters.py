from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from persona_dock.adapters.hermes import HermesAdapter
from persona_dock.adapters.openclaw import OpenClawAdapter


def run(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(arguments))
    return subprocess.run(
        arguments,
        check=check,
        capture_output=True,
        text=True,
        timeout=120,
    )


def write_script(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def main() -> int:
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("docker executable is required")
    run([docker, "info"])
    name = "personadock-contract-" + uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix="personadock-docker-contract-") as directory:
        root = Path(directory)
        hermes_script = root / "hermes"
        openclaw_script = root / "openclaw"
        write_script(
            hermes_script,
            """#!/bin/sh
set -eu
if [ "${1:-}" = "version" ]; then
  echo "Hermes 1.0.0"
elif [ "${1:-}" = "profile" ] && [ "${2:-}" = "list" ]; then
  echo "default"
elif [ "${1:-}" = "profile" ] && [ "${2:-}" = "show" ]; then
  echo "Profile: ${3:-default}"
  echo "Path: /root/.hermes/profiles/${3:-default}"
elif [ "${1:-}" = "profile" ] && [ "${2:-}" = "info" ]; then
  echo "Name: ${3:-default}"
else
  echo "{}"
fi
""",
        )
        write_script(
            openclaw_script,
            """#!/bin/sh
set -eu
if [ "${1:-}" = "--version" ]; then
  echo "OpenClaw 1.0.0"
elif [ "${1:-}" = "agents" ] && [ "${2:-}" = "list" ]; then
  echo '{"agents":[]}'
else
  echo '{}'
fi
""",
        )
        try:
            run(
                [
                    docker,
                    "run",
                    "--detach",
                    "--name",
                    name,
                    "alpine:3.20",
                    "sh",
                    "-c",
                    "while true; do sleep 3600; done",
                ]
            )
            run([docker, "cp", str(hermes_script), f"{name}:/usr/local/bin/hermes"])
            run([docker, "cp", str(openclaw_script), f"{name}:/usr/local/bin/openclaw"])
            run(
                [
                    docker,
                    "exec",
                    name,
                    "chmod",
                    "+x",
                    "/usr/local/bin/hermes",
                    "/usr/local/bin/openclaw",
                ]
            )

            hermes = HermesAdapter(container=name, docker_executable=docker)
            hermes_result = hermes.doctor()
            if not hermes_result.available or hermes_result.status != "ready":
                raise AssertionError(hermes_result.to_dict())
            if hermes_result.details.get("container") != name:
                raise AssertionError("Hermes Doctor did not retain container identity")

            openclaw = OpenClawAdapter(container=name, docker_executable=docker)
            openclaw_result = openclaw.doctor()
            if not openclaw_result.available or openclaw_result.status != "ready":
                raise AssertionError(openclaw_result.to_dict())
            if openclaw_result.details.get("transport") != "docker":
                raise AssertionError("OpenClaw Doctor did not report Docker transport")

            source = root / "source.txt"
            source.write_text("PersonaDock Docker round trip", encoding="utf-8")
            hermes.runner.docker_copy_to(source, "/tmp/hermes-round-trip.txt")
            hermes_copy = root / "hermes-copy.txt"
            hermes.runner.docker_copy_from("/tmp/hermes-round-trip.txt", hermes_copy)
            if hermes_copy.read_text(encoding="utf-8") != source.read_text(encoding="utf-8"):
                raise AssertionError("Hermes Docker copy round trip changed content")

            openclaw.runner.copy_to(source, "/tmp/openclaw-round-trip.txt")
            openclaw_copy = root / "openclaw-copy.txt"
            openclaw.runner.copy_from("/tmp/openclaw-round-trip.txt", openclaw_copy)
            if openclaw_copy.read_text(encoding="utf-8") != source.read_text(encoding="utf-8"):
                raise AssertionError("OpenClaw Docker copy round trip changed content")

            print("Verified native Hermes/OpenClaw Docker Adapter contracts")
            return 0
        finally:
            run([docker, "rm", "--force", name], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
