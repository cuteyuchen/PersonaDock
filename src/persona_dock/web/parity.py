from __future__ import annotations

import argparse
from typing import Any

from persona_dock import stable_cli

from .capabilities import CAPABILITIES


CLI_TOP_LEVEL_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "init": ("persona.init",),
    "distill": ("persona.distill",),
    "build": ("persona.build",),
    "pack": ("persona.pack",),
    "inspect": ("package.inspect",),
    "validate": ("persona.validate",),
    "migrate": ("persona.migrate",),
    "diff": ("persona.diff",),
    "test": ("persona.test",),
    "doctor": ("system.doctor",),
    "discover": ("runtime.discover",),
    "persona": ("persona.list", "persona.show", "persona.register"),
    "instances": ("runtime.instances",),
    "adopt": ("runtime.adopt",),
    "export": ("persona.export",),
    "export-public": ("persona.export-public",),
    "deploy": ("deployment.plan", "deployment.apply"),
    "install": ("deployment.install-alias",),
    "rollback": ("deployment.rollback",),
    "uninstall": ("deployment.uninstall",),
    "status": ("deployment.status",),
    "serve": ("system.serve",),
    "hermes": ("adapter.list", "adapter.doctor", "deployment.apply", "sync.memory"),
    "openclaw": ("adapter.list", "adapter.doctor", "deployment.apply", "sync.memory"),
    "sync": ("sync.memory",),
    "session": ("sync.sessions",),
    "adapter": ("adapter.list", "adapter.show", "adapter.doctor"),
    "skill": ("skill.install",),
    "trust": ("trust.keygen", "trust.sign", "trust.verify"),
    "backup": ("backup.create", "backup.inspect", "backup.restore"),
    "character-card": (
        "character-card.inspect",
        "character-card.import",
        "character-card.export",
    ),
}


def top_level_cli_commands() -> set[str]:
    parser = stable_cli.build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(str(value) for value in action.choices)
    raise RuntimeError("PersonaDock CLI parser has no top-level subcommands")


def parity_report() -> dict[str, Any]:
    commands = top_level_cli_commands()
    mapped_commands = set(CLI_TOP_LEVEL_CAPABILITIES)
    capabilities = {item.id: item for item in CAPABILITIES}
    missing_commands = sorted(commands - mapped_commands)
    stale_commands = sorted(mapped_commands - commands)
    missing_capabilities: dict[str, list[str]] = {}
    non_ready_capabilities: dict[str, list[str]] = {}
    for command, capability_ids in CLI_TOP_LEVEL_CAPABILITIES.items():
        for capability_id in capability_ids:
            capability = capabilities.get(capability_id)
            if capability is None:
                missing_capabilities.setdefault(command, []).append(capability_id)
            elif capability.status == "planned":
                non_ready_capabilities.setdefault(command, []).append(capability_id)
    return {
        "commands": sorted(commands),
        "mapped_commands": sorted(mapped_commands),
        "missing_commands": missing_commands,
        "stale_commands": stale_commands,
        "missing_capabilities": missing_capabilities,
        "non_ready_capabilities": non_ready_capabilities,
        "complete": not any(
            (missing_commands, stale_commands, missing_capabilities, non_ready_capabilities)
        ),
    }


def validate_cli_web_parity() -> list[str]:
    report = parity_report()
    errors: list[str] = []
    if report["missing_commands"]:
        errors.append("CLI commands without Web mapping: " + ", ".join(report["missing_commands"]))
    if report["stale_commands"]:
        errors.append("Web parity map contains stale CLI commands: " + ", ".join(report["stale_commands"]))
    for command, values in report["missing_capabilities"].items():
        errors.append(f"{command} maps to missing capabilities: {', '.join(values)}")
    for command, values in report["non_ready_capabilities"].items():
        errors.append(f"{command} maps only to planned capabilities: {', '.join(values)}")
    return errors


__all__ = [
    "CLI_TOP_LEVEL_CAPABILITIES",
    "parity_report",
    "top_level_cli_commands",
    "validate_cli_web_parity",
]
