from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .compiler import compile_project
from .distill import distill_chat
from .installer import install_package, rollback, status, uninstall
from .packaging import export_public, inspect_package, pack_project
from .project import find_project, init_project, validate_project
from .skill_install import TARGETS as SKILL_TARGETS
from .skill_install import install_skill


def _print_status() -> int:
    records = status()
    if not records:
        print("No PersonaDock installations found.")
        return 0
    for record in records:
        destination = record["destination"]
        if record.get("transport") == "docker":
            destination = f"docker://{record.get('container')}{destination}"
        print(
            f"{record['id']}@{record['version']}  {record['target']:<9}  "
            f"{destination}"
        )
    return 0


def _destination(path: str | None, container: str | None) -> str | Path | None:
    if not path:
        return None
    return path if container else Path(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="personadock",
        description="Create, package, and install private portable AI personas.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("init", help="create a local persona project")
    command.add_argument("destination")
    command.add_argument("--id", required=True)
    command.add_argument("--name", required=True)
    command.add_argument("--locale", default="zh-CN")
    command.add_argument("--force", action="store_true")

    command = sub.add_parser(
        "distill",
        help="lightweight fallback distillation for simple speaker-prefixed text",
    )
    command.add_argument("input")
    command.add_argument("destination")
    command.add_argument("--id", required=True)
    command.add_argument("--name", required=True)
    command.add_argument("--speaker", required=True)
    command.add_argument("--locale", default="zh-CN")

    skill = sub.add_parser("skill", help="manage the PersonaDock AI editor Skill")
    skill_sub = skill.add_subparsers(dest="skill_command", required=True)
    command = skill_sub.add_parser(
        "install",
        help="install the unified persona-builder Skill into an AI editor",
    )
    command.add_argument("--target", required=True, choices=sorted(SKILL_TARGETS))
    command.add_argument("--scope", choices=["project", "global"], default="global")
    command.add_argument("--path", help="custom parent directory for the installed Skill")

    command = sub.add_parser("validate", help="validate a local persona project")
    command.add_argument("project", nargs="?", default=".")

    command = sub.add_parser("build", help="compile SOUL, Skill, and Memory targets")
    command.add_argument("project", nargs="?", default=".")
    command.add_argument("--output")
    command.add_argument("--target", action="append", choices=["hermes", "openclaw", "generic"])

    command = sub.add_parser("pack", help="create a portable .personapack archive")
    command.add_argument("project", nargs="?", default=".")
    command.add_argument("--output")
    command.add_argument("--target", action="append", choices=["hermes", "openclaw", "generic"])

    command = sub.add_parser("inspect", help="verify and show PersonaPack metadata")
    command.add_argument("package")

    command = sub.add_parser("install", help="install a PersonaPack into an agent")
    command.add_argument("package")
    command.add_argument("--target", required=True, choices=["hermes", "openclaw", "generic"])
    command.add_argument(
        "--path",
        help="custom host destination, or an absolute path inside --container",
    )
    command.add_argument(
        "--container",
        help="running Docker container name; install through docker exec and docker cp",
    )

    command = sub.add_parser("rollback", help="restore files replaced by PersonaDock")
    command.add_argument("--target", required=True, choices=["hermes", "openclaw", "generic"])
    command.add_argument(
        "--path",
        help="custom host destination, or the same absolute path used inside --container",
    )
    command.add_argument("--container", help="running Docker container used for the installation")

    command = sub.add_parser("uninstall", help="remove an installed persona")
    command.add_argument("--target", required=True, choices=["hermes", "openclaw", "generic"])
    command.add_argument(
        "--path",
        help="custom host destination, or the same absolute path used inside --container",
    )
    command.add_argument("--container", help="running Docker container used for the installation")
    command.add_argument("--no-restore", action="store_true")

    sub.add_parser("status", help="show managed installations")

    command = sub.add_parser("export-public", help="export a memory-free public project build")
    command.add_argument("project", nargs="?", default=".")
    command.add_argument("--output")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "init":
        result = init_project(Path(args.destination), args.id, args.name, args.locale, args.force)
        print(result)
        return 0
    if args.command == "distill":
        result = distill_chat(Path(args.input), Path(args.destination), args.id, args.name, args.speaker, args.locale)
        print(result)
        return 0
    if args.command == "skill" and args.skill_command == "install":
        result = install_skill(
            args.target,
            args.scope,
            Path(args.path) if args.path else None,
        )
        print(result)
        return 0
    if args.command == "validate":
        errors = validate_project(Path(args.project))
        if errors:
            print("INVALID")
            for error in errors:
                print(f"- {error}")
            return 1
        print(f"OK {find_project(Path(args.project))}")
        return 0
    if args.command == "build":
        result = compile_project(Path(args.project), Path(args.output) if args.output else None, args.target)
        print(result)
        return 0
    if args.command == "pack":
        result = pack_project(Path(args.project), Path(args.output) if args.output else None, args.target)
        print(result)
        return 0
    if args.command == "inspect":
        print(json.dumps(inspect_package(Path(args.package)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "install":
        result = install_package(
            Path(args.package),
            args.target,
            _destination(args.path, args.container),
            args.container,
        )
        print(result)
        return 0
    if args.command == "rollback":
        print(rollback(args.target, _destination(args.path, args.container), args.container))
        return 0
    if args.command == "uninstall":
        print(
            uninstall(
                args.target,
                _destination(args.path, args.container),
                restore_previous=not args.no_restore,
                container=args.container,
            )
        )
        return 0
    if args.command == "status":
        return _print_status()
    if args.command == "export-public":
        result = export_public(Path(args.project), Path(args.output) if args.output else None)
        print(result)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
