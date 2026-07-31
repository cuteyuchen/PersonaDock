from __future__ import annotations

import argparse
import os
import tempfile
import traceback
from pathlib import Path

from persona_dock import __version__
from verify_binary import _check_help, _run, _verify_1_0_workflow, _verify_web


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a PersonaDock release executable.")
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

        version_output = str(_run(binary, runtime_root, environment, ["--version"]))
        if __version__ not in version_output:
            raise AssertionError(
                f"standalone version mismatch: expected {__version__!r}, got {version_output!r}"
            )

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
        if not isinstance(adapters, dict) or adapters.get("adapter_api_version") != "1.0":
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

    print(f"Verified PersonaDock {__version__} standalone binary: {binary}")
    return 0


def _persist_failure() -> None:
    diagnostics = Path("build/personadock/warn-personadock.txt")
    diagnostics.parent.mkdir(parents=True, exist_ok=True)
    with diagnostics.open("a", encoding="utf-8") as stream:
        stream.write("\n\n=== PersonaDock release verification failure ===\n")
        stream.write(traceback.format_exc())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:
        _persist_failure()
        raise
