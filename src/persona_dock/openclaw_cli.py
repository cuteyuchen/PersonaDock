from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from persona_dock import hermes_cli
from persona_dock.adapters.openclaw import OpenClawAdapter, OpenClawAdapterError
from persona_dock.openclaw_deployment import (
    apply_openclaw_deployment,
    plan_openclaw_deployment,
    rollback_openclaw_deployment,
)
from persona_dock.openclaw_memory import (
    pull_openclaw_memory_candidates,
    push_openclaw_shared_memory,
)


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("PersonaDock parser has no subcommands")


def _extend_deployment_parser(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--agent",
        help="native OpenClaw Agent ID; defaults to the Persona ID",
    )
    command.add_argument(
        "--workspace",
        help="explicit workspace for a new Agent; existing Agents must match CLI discovery",
    )
    command.add_argument("--model", help="OpenClaw model ID for a newly created Agent")
    command.add_argument(
        "--bind",
        action="append",
        default=[],
        help="OpenClaw channel binding for a new Agent; repeatable",
    )
    command.add_argument(
        "--take-ownership",
        action="store_true",
        help="adopt existing SOUL/IDENTITY/Persona Skill files after reviewing the plan",
    )
    command.add_argument(
        "--ssh-host",
        help="run OpenClaw CLI and workspace operations over SSH",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = hermes_cli.build_parser()
    sub = _subparsers(parser)
    _extend_deployment_parser(sub.choices["deploy"])
    _extend_deployment_parser(sub.choices["install"])

    openclaw = sub.add_parser("openclaw", help="manage native OpenClaw Agents and Workspaces")
    openclaw_sub = openclaw.add_subparsers(dest="openclaw_command", required=True)

    command = openclaw_sub.add_parser("doctor", help="check OpenClaw CLI and Agent discovery")
    command.add_argument("--container")
    command.add_argument("--ssh-host")
    command.add_argument("--json", action="store_true")

    command = openclaw_sub.add_parser("agents", help="list OpenClaw Agents with workspace/state separation")
    command.add_argument("--container")
    command.add_argument("--ssh-host")
    command.add_argument("--json", action="store_true")

    command = openclaw_sub.add_parser("rollback", help="restore a workspace snapshot or delete a created Agent")
    command.add_argument("--agent", required=True)
    command.add_argument("--snapshot")
    command.add_argument("--workspace")
    command.add_argument("--delete-agent", action="store_true")
    command.add_argument("--container")
    command.add_argument("--ssh-host")
    command.add_argument("--json", action="store_true")

    memory = openclaw_sub.add_parser("memory", help="pull or push OpenClaw workspace memory")
    memory_sub = memory.add_subparsers(dest="openclaw_memory_command", required=True)

    command = memory_sub.add_parser("pull", help="import workspace memory as unreviewed local candidates")
    command.add_argument("persona_id")
    command.add_argument("--agent", required=True)
    command.add_argument("--container")
    command.add_argument("--ssh-host")
    command.add_argument("--json", action="store_true")

    command = memory_sub.add_parser("push", help="push reviewed memory and rebuild the OpenClaw index")
    command.add_argument("persona_id")
    command.add_argument("--agent", required=True)
    command.add_argument("--container")
    command.add_argument("--ssh-host")
    command.add_argument("--yes", action="store_true")
    command.add_argument("--json", action="store_true")

    return parser


def _print_plan(value: dict[str, Any]) -> None:
    transport = value["transport"]
    target = value["agent"]
    if value.get("container"):
        target = f"docker://{value['container']}/{target}"
    elif value.get("ssh_host"):
        target = f"ssh://{value['ssh_host']}/{target}"
    print(f"PersonaPack: {value['persona_id']}@{value['persona_version']}")
    print(f"OpenClaw Agent: {target}")
    print(f"Transport: {transport}")
    print(f"Existing Agent: {'yes' if value['existing_agent'] else 'no'}")
    print(f"Workspace: {value['workspace']}")
    print(f"State directory: {value.get('state_directory') or 'created/managed by OpenClaw'}")
    print(f"Overlay: {value['artifact']['path']}")
    if value.get("snapshot_path"):
        print(f"Pre-deployment snapshot: {value['snapshot_path']}")
    if value.get("conflicts"):
        print("Ownership conflicts:")
        for item in value["conflicts"]:
            print(f"- {item}")
    print("\nOperations:")
    for command in value["commands"]:
        if command and command[0] == "workspace-overlay":
            print(f"- copy managed overlay {command[1]} -> {command[2]}")
        else:
            print("- openclaw " + " ".join(command))
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


def _adapter(args: argparse.Namespace) -> OpenClawAdapter:
    return OpenClawAdapter(
        container=getattr(args, "container", None),
        ssh_host=getattr(args, "ssh_host", None),
    )


def _run_native_deployment(args: argparse.Namespace) -> int:
    if args.path:
        raise ValueError("--path is only valid with --legacy-filesystem")
    if args.profile or args.activate or args.alias:
        raise ValueError("--profile, --activate, and --alias are only valid for native Hermes deployment")
    adapter = _adapter(args)
    plan = plan_openclaw_deployment(
        Path(args.package),
        agent=args.agent,
        agent_explicit=args.agent is not None,
        workspace=args.workspace,
        model=args.model,
        bindings=args.bind,
        take_ownership=args.take_ownership,
        container=args.container,
        ssh_host=args.ssh_host,
        adapter=adapter,
    )
    value = plan.to_dict()
    if args.json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        _print_plan(value)
    if args.dry_run:
        return 0
    if not _confirm("\nApply this native OpenClaw deployment? [y/N] ", yes=args.yes):
        print("Deployment cancelled.")
        return 1
    result = apply_openclaw_deployment(plan, adapter=adapter)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(
            f"\nDeployed {result.persona_id}@{result.persona_version} "
            f"to OpenClaw Agent {result.agent}."
        )
        print(f"Workspace: {result.workspace}")
        print(f"State directory: {result.state_directory or 'reported by OpenClaw after creation'}")
        if result.snapshot_path:
            print(f"Snapshot: {result.snapshot_path}")
    return 0


def _run_openclaw_command(args: argparse.Namespace) -> int:
    adapter = _adapter(args)
    if args.openclaw_command == "doctor":
        value = adapter.doctor().to_dict()
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value["message"])
        return 0 if value["available"] else 1
    if args.openclaw_command == "agents":
        values = [agent.to_dict() for agent in adapter.list_agents()]
        if args.json:
            print(json.dumps(values, ensure_ascii=False, indent=2))
        else:
            if not values:
                print("No OpenClaw Agents found.")
            for value in values:
                print(f"{value['id']:<20} {value['name']}")
                print(f"  workspace: {value['workspace']}")
                print(f"  state: {value.get('agent_dir') or 'not reported'}")
                print(f"  bindings: {len(value.get('bindings', []))}")
        return 0
    if args.openclaw_command == "rollback":
        value = rollback_openclaw_deployment(
            agent=args.agent,
            snapshot=args.snapshot,
            workspace=args.workspace,
            delete_agent=args.delete_agent,
            container=args.container,
            ssh_host=args.ssh_host,
            adapter=adapter,
        )
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else f"{value['action']} {args.agent}")
        return 0
    if args.openclaw_command == "memory":
        if args.openclaw_memory_command == "pull":
            value = pull_openclaw_memory_candidates(
                args.persona_id,
                agent_id=args.agent,
                container=args.container,
                ssh_host=args.ssh_host,
                adapter=adapter,
            )
        else:
            if not _confirm(
                "Push reviewed shared memory and rebuild the OpenClaw index? [y/N] ",
                yes=args.yes,
            ):
                print("Memory push cancelled.")
                return 1
            value = push_openclaw_shared_memory(
                args.persona_id,
                agent_id=args.agent,
                container=args.container,
                ssh_host=args.ssh_host,
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
            if args.target == "openclaw" and not args.legacy_filesystem:
                if args.command == "install":
                    print(
                        "Warning: `personadock install` is deprecated; use `personadock deploy`.",
                        file=sys.stderr,
                    )
                return _run_native_deployment(args)
            if any(
                (
                    args.agent,
                    args.workspace,
                    args.model,
                    args.bind,
                    args.take_ownership,
                    args.ssh_host,
                )
            ):
                raise ValueError(
                    "--agent, --workspace, --model, --bind, --take-ownership, and --ssh-host "
                    "are only valid for native OpenClaw deployment"
                )
            filtered = list(argv if argv is not None else sys.argv[1:])
            filtered = [item for item in filtered if item != "--legacy-filesystem"]
            return hermes_cli.main(filtered)
        if args.command == "openclaw":
            return _run_openclaw_command(args)
        return hermes_cli.main(argv)
    except OpenClawAdapterError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
