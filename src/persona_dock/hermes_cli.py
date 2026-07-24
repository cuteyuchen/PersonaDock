from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from persona_dock import canonical_cli
from persona_dock.adapters.hermes import HermesAdapter, HermesAdapterError
from persona_dock.hermes_deployment import (
    apply_hermes_deployment,
    plan_hermes_deployment,
    rollback_hermes_deployment,
)
from persona_dock.hermes_memory import (
    pull_hermes_memory_candidates,
    push_hermes_shared_memory,
)


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("PersonaDock parser has no subcommands")


def _extend_deployment_parser(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--profile",
        help="native Hermes profile name; defaults to the Persona ID",
    )
    command.add_argument(
        "--activate",
        action="store_true",
        help="make the deployed Hermes profile active after verification",
    )
    command.add_argument(
        "--alias",
        action="store_true",
        help="ask Hermes to create a shell alias for the profile",
    )
    command.add_argument(
        "--legacy-filesystem",
        action="store_true",
        help="use the deprecated direct filesystem adapter instead of Hermes Profile Distribution",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = canonical_cli.build_parser()
    sub = _subparsers(parser)
    _extend_deployment_parser(sub.choices["deploy"])
    _extend_deployment_parser(sub.choices["install"])

    hermes = sub.add_parser("hermes", help="manage native Hermes Profile deployments")
    hermes_sub = hermes.add_subparsers(dest="hermes_command", required=True)

    command = hermes_sub.add_parser("doctor", help="check Hermes CLI and Profile Distribution support")
    command.add_argument("--container")
    command.add_argument("--json", action="store_true")

    command = hermes_sub.add_parser("profiles", help="list Hermes profiles through the Hermes CLI")
    command.add_argument("--container")
    command.add_argument("--json", action="store_true")

    command = hermes_sub.add_parser("rollback", help="restore or delete a native Hermes deployment")
    command.add_argument("--profile", required=True)
    command.add_argument("--snapshot")
    command.add_argument("--container")
    command.add_argument("--activate", action="store_true")
    command.add_argument("--json", action="store_true")

    memory = hermes_sub.add_parser("memory", help="pull or push Hermes built-in memory")
    memory_sub = memory.add_subparsers(dest="hermes_memory_command", required=True)

    command = memory_sub.add_parser("pull", help="import Hermes memory as unreviewed local candidates")
    command.add_argument("persona_id")
    command.add_argument("--profile", required=True)
    command.add_argument("--container")
    command.add_argument("--json", action="store_true")

    command = memory_sub.add_parser("push", help="push reviewed shared memory into a managed Hermes block")
    command.add_argument("persona_id")
    command.add_argument("--profile", required=True)
    command.add_argument("--container")
    command.add_argument("--yes", action="store_true")
    command.add_argument("--json", action="store_true")

    return parser


def _print_native_plan(value: dict[str, Any]) -> None:
    location = (
        f"docker://{value['container']}/{value['profile']}"
        if value.get("container")
        else value["profile"]
    )
    print(f"PersonaPack: {value['persona_id']}@{value['persona_version']}")
    print(f"Hermes profile: {location}")
    print(f"Existing profile: {'yes' if value['existing_profile'] else 'no'}")
    print(f"Activate: {'yes' if value['activate'] else 'no'}")
    print(f"Artifact: {value['artifact']['path']}")
    if value.get("snapshot_path"):
        print(f"Pre-deployment snapshot: {value['snapshot_path']}")
    print("\nHermes commands:")
    for command in value["commands"]:
        print("- hermes " + " ".join(command))
    print("\nPreserved:")
    for item in value["preserves"]:
        print(f"- {item}")
    if value["warnings"]:
        print("\nWarnings:")
        for item in value["warnings"]:
            print(f"- {item}")


def _confirm(prompt: str, *, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise ValueError("operation requires --yes when standard input is not interactive")
    return input(prompt).strip().lower() in {"y", "yes"}


def _run_native_deployment(args: argparse.Namespace) -> int:
    if args.path:
        raise ValueError("--path is only valid with --legacy-filesystem")
    adapter = HermesAdapter(container=args.container)
    plan = plan_hermes_deployment(
        Path(args.package),
        profile=args.profile,
        profile_explicit=args.profile is not None,
        activate=args.activate,
        alias=args.alias,
        container=args.container,
        adapter=adapter,
    )
    value = plan.to_dict()
    if args.json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        _print_native_plan(value)
    if args.dry_run:
        return 0
    if not _confirm("\nApply this native Hermes deployment? [y/N] ", yes=args.yes):
        print("Deployment cancelled.")
        return 1
    result = apply_hermes_deployment(plan, adapter=adapter)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"\nDeployed {result.persona_id}@{result.persona_version} to Hermes profile {result.profile}.")
        if result.snapshot_path:
            print(f"Snapshot: {result.snapshot_path}")
    return 0


def _run_hermes_command(args: argparse.Namespace) -> int:
    adapter = HermesAdapter(container=getattr(args, "container", None))
    if args.hermes_command == "doctor":
        value = adapter.doctor().to_dict()
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value["message"])
        return 0 if value["available"] else 1
    if args.hermes_command == "profiles":
        values = [profile.to_dict() for profile in adapter.list_profiles()]
        if args.json:
            print(json.dumps(values, ensure_ascii=False, indent=2))
        else:
            if not values:
                print("No Hermes profiles found.")
            for value in values:
                marker = "*" if value["active"] else " "
                distribution = value.get("distribution", {}).get("version")
                suffix = f"  distribution {distribution}" if distribution else ""
                print(f"{marker} {value['name']}{suffix}")
                if value.get("path"):
                    print(f"  {value['path']}")
        return 0
    if args.hermes_command == "rollback":
        value = rollback_hermes_deployment(
            profile=args.profile,
            snapshot=args.snapshot,
            container=args.container,
            activate=args.activate,
            adapter=adapter,
        )
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else f"{value['action']} {args.profile}")
        return 0
    if args.hermes_command == "memory":
        if args.hermes_memory_command == "pull":
            value = pull_hermes_memory_candidates(
                args.persona_id,
                profile=args.profile,
                container=args.container,
                adapter=adapter,
            )
        else:
            if not _confirm(
                "Push reviewed shared memory to the Hermes profile? [y/N] ",
                yes=args.yes,
            ):
                print("Memory push cancelled.")
                return 1
            value = push_hermes_shared_memory(
                args.persona_id,
                profile=args.profile,
                container=args.container,
                adapter=adapter,
            )
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value)
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"deploy", "install"}:
            if args.target == "hermes" and not args.legacy_filesystem:
                if args.command == "install":
                    print(
                        "Warning: `personadock install` is deprecated; use `personadock deploy`.",
                        file=sys.stderr,
                    )
                return _run_native_deployment(args)
            if args.profile or args.activate or args.alias:
                raise ValueError("--profile, --activate, and --alias are only valid for native Hermes deployment")
            filtered = list(argv if argv is not None else sys.argv[1:])
            filtered = [item for item in filtered if item != "--legacy-filesystem"]
            return canonical_cli.main(filtered)
        if args.command == "hermes":
            return _run_hermes_command(args)
        return canonical_cli.main(argv)
    except HermesAdapterError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
