from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .compiler import compile_project
from .deployment.plans import apply_deployment_plan, build_deployment_plan
from .discovery import discover_runtime_instances
from .distill import distill_chat
from .doctor import doctor_report, render_doctor
from .installer import rollback, status, uninstall
from .io import load_yaml
from .packaging import export_public, inspect_package, pack_project
from .project import PROJECT_FILE, find_project, init_project, validate_project
from .registry import RegistryService
from .skill_install import TARGETS as SKILL_TARGETS
from .skill_install import install_skill


AGENT_TARGETS = ["hermes", "openclaw", "generic"]


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


def _add_deployment_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("package")
    command.add_argument("--target", required=True, choices=AGENT_TARGETS)
    command.add_argument(
        "--path",
        help="explicit host destination, or an absolute path inside --container",
    )
    command.add_argument(
        "--container",
        help="running Docker container name; legacy Docker mode requires --path",
    )
    command.add_argument("--dry-run", action="store_true", help="print the plan without writing files")
    command.add_argument("--yes", action="store_true", help="apply the plan without an interactive prompt")
    command.add_argument("--json", action="store_true", help="print the deployment plan as JSON")


def _print_plan(plan: dict[str, object]) -> None:
    print(f"PersonaPack: {plan['package_id']}@{plan['package_version']}")
    print(f"Target: {plan['target']} via {plan['adapter']}")
    if plan.get("container"):
        print(f"Destination: docker://{plan['container']}{plan['destination']}")
    else:
        print(f"Destination: {plan['destination']}")
    print(f"Resolution source: {plan['destination_source']}")
    print("\nOperations:")
    operations = plan.get("operations", [])
    for operation in operations:
        marker = "replace" if operation.get("exists") is True else "create"
        if operation.get("exists") is None:
            marker = "inspect during apply"
        print(f"- {marker}: {operation['destination']}")
    print("\nPreserved:")
    for item in plan.get("preserves", []):
        print(f"- {item}")
    print("\nWarnings:")
    for item in plan.get("warnings", []):
        print(f"- {item}")


def _run_deployment(args: argparse.Namespace) -> int:
    plan = build_deployment_plan(
        Path(args.package),
        args.target,
        _destination(args.path, args.container),
        args.container,
    )
    rendered = plan.to_dict()
    if args.json:
        print(json.dumps(rendered, ensure_ascii=False, indent=2))
    else:
        _print_plan(rendered)

    if args.dry_run:
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            raise ValueError("deployment requires --yes when standard input is not interactive")
        answer = input("\nApply this deployment plan? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Deployment cancelled.")
            return 1

    result = apply_deployment_plan(plan)
    print(f"\nInstalled at {result}")
    return 0


def _register_project(project_path: Path) -> dict[str, Any]:
    root = find_project(project_path)
    project = load_yaml(root / PROJECT_FILE)
    record = RegistryService().register_persona(
        persona_id=str(project["id"]),
        name=str(project["name"]),
        version=str(project["version"]),
        source_path=root,
        schema_version=int(project.get("schema_version", 2)),
        summary=str(project.get("summary", "")),
    )
    return record.to_dict()


def _print_personas(json_output: bool) -> int:
    values = [record.to_dict() for record in RegistryService().list_personas()]
    if json_output:
        print(json.dumps(values, ensure_ascii=False, indent=2))
        return 0
    if not values:
        print("No personas registered. Create one with `personadock init`.")
        return 0
    for value in values:
        print(f"{value['id']:<24} {value['version']:<10} {value['name']}")
        if value.get("source_path"):
            print(f"  {value['source_path']}")
    return 0


def _show_persona(persona_id: str, json_output: bool) -> int:
    service = RegistryService()
    record = service.get_persona(persona_id)
    if record is None:
        raise ValueError(f"persona is not registered: {persona_id}")
    value = {
        **record.to_dict(),
        "bindings": [binding.to_dict() for binding in service.list_bindings(persona_id)],
    }
    if json_output:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(f"{value['name']} ({value['id']})")
        print(f"Version: {value['version']}")
        print(f"Schema: {value['schema_version']}")
        print(f"Source: {value.get('source_path') or 'not bound'}")
        print(f"Bindings: {len(value['bindings'])}")
        if value.get("summary"):
            print(f"Summary: {value['summary']}")
    return 0


def _print_instances(adapter: str | None, managed: bool | None, json_output: bool) -> int:
    values = [
        record.to_dict()
        for record in RegistryService().list_runtime_instances(adapter=adapter, managed=managed)
    ]
    if json_output:
        print(json.dumps(values, ensure_ascii=False, indent=2))
        return 0
    if not values:
        print("No runtime instances found. Run `personadock discover`.")
        return 0
    for value in values:
        state = "managed" if value["managed"] else "unmanaged"
        print(
            f"{value['adapter']:<10} {value['platform_instance_id']:<20} "
            f"{state:<10} {value['display_name']}"
        )
        print(f"  {value['transport']}://{value['location']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="personadock",
        description="Build and manage portable AI personas through a local control plane.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("init", help="create and register a local persona project")
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
    command.add_argument("--target", action="append", choices=AGENT_TARGETS)

    command = sub.add_parser("pack", help="create a portable .personapack archive")
    command.add_argument("project", nargs="?", default=".")
    command.add_argument("--output")
    command.add_argument("--target", action="append", choices=AGENT_TARGETS)

    command = sub.add_parser("inspect", help="verify and show PersonaPack metadata")
    command.add_argument("package")

    command = sub.add_parser("doctor", help="inspect platform commands and safe deployment targets")
    command.add_argument("--json", action="store_true")

    command = sub.add_parser("discover", help="read-only discovery of Hermes Profiles and OpenClaw Agents")
    command.add_argument("--target", choices=["hermes", "openclaw"])
    command.add_argument("--json", action="store_true")

    persona = sub.add_parser("persona", help="query the local Persona Registry")
    persona_sub = persona.add_subparsers(dest="persona_command", required=True)
    command = persona_sub.add_parser("list", help="list registered personas")
    command.add_argument("--json", action="store_true")
    command = persona_sub.add_parser("show", help="show one registered persona")
    command.add_argument("persona_id")
    command.add_argument("--json", action="store_true")
    command = persona_sub.add_parser("register", help="register an existing PersonaDock project")
    command.add_argument("project", nargs="?", default=".")
    command.add_argument("--json", action="store_true")

    command = sub.add_parser("instances", help="list discovered runtime instances")
    command.add_argument("--adapter", choices=["hermes", "openclaw"])
    managed = command.add_mutually_exclusive_group()
    managed.add_argument("--managed", action="store_true")
    managed.add_argument("--unmanaged", action="store_true")
    command.add_argument("--json", action="store_true")

    command = sub.add_parser("deploy", help="plan and deploy a PersonaPack safely")
    _add_deployment_arguments(command)

    command = sub.add_parser(
        "install",
        help="deprecated alias for deploy; retained for migration compatibility",
    )
    _add_deployment_arguments(command)

    command = sub.add_parser("serve", help="start the local PersonaDock Web control plane")
    command.add_argument("--host", default="127.0.0.1")
    command.add_argument("--port", type=int, default=8732)
    command.add_argument("--token", help="bearer token; required for non-loopback bindings")
    command.add_argument("--no-browser", action="store_true")

    command = sub.add_parser("rollback", help="restore files replaced by PersonaDock")
    command.add_argument("--target", required=True, choices=AGENT_TARGETS)
    command.add_argument(
        "--path",
        help="custom host destination, or the same absolute path used inside --container",
    )
    command.add_argument("--container", help="running Docker container used for the installation")

    command = sub.add_parser("uninstall", help="remove an installed persona")
    command.add_argument("--target", required=True, choices=AGENT_TARGETS)
    command.add_argument(
        "--path",
        help="custom host destination, or the same absolute path used inside --container",
    )
    command.add_argument("--container", help="running Docker container used for the installation")
    command.add_argument("--no-restore", action="store_true")

    sub.add_parser("status", help="show managed legacy installations")

    command = sub.add_parser("export-public", help="export a memory-free public project build")
    command.add_argument("project", nargs="?", default=".")
    command.add_argument("--output")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "init":
        result = init_project(Path(args.destination), args.id, args.name, args.locale, args.force)
        _register_project(result)
        print(result)
        return 0
    if args.command == "distill":
        result = distill_chat(Path(args.input), Path(args.destination), args.id, args.name, args.speaker, args.locale)
        _register_project(result)
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
        _register_project(Path(args.project))
        print(result)
        return 0
    if args.command == "pack":
        result = pack_project(Path(args.project), Path(args.output) if args.output else None, args.target)
        _register_project(Path(args.project))
        print(result)
        return 0
    if args.command == "inspect":
        print(json.dumps(inspect_package(Path(args.package)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "doctor":
        report = doctor_report()
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_doctor(report))
        return 0
    if args.command == "discover":
        report = discover_runtime_instances(args.target)
        if args.json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"Scanned: {', '.join(report.scanned_adapters)}")
            print(f"Discovered: {len(report.instances)}")
            for instance in report.instances:
                state = "managed" if instance.managed else "unmanaged"
                print(
                    f"- {instance.adapter}/{instance.platform_instance_id} "
                    f"[{state}] {instance.display_name}"
                )
                print(f"  {instance.location}")
            for warning in report.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
        return 0
    if args.command == "persona":
        if args.persona_command == "list":
            return _print_personas(args.json)
        if args.persona_command == "show":
            return _show_persona(args.persona_id, args.json)
        if args.persona_command == "register":
            value = _register_project(Path(args.project))
            print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value["id"])
            return 0
    if args.command == "instances":
        managed_filter = True if args.managed else False if args.unmanaged else None
        return _print_instances(args.adapter, managed_filter, args.json)
    if args.command in {"deploy", "install"}:
        if args.command == "install":
            print("Warning: `personadock install` is deprecated; use `personadock deploy`.", file=sys.stderr)
        return _run_deployment(args)
    if args.command == "serve":
        from .web import run_server

        run_server(
            host=args.host,
            port=args.port,
            token=args.token,
            open_browser=not args.no_browser,
        )
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
