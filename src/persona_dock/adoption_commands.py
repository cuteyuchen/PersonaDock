from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from persona_dock.adoption import adopt_runtime_instance, adoption_preview
from persona_dock.exports import EXPORT_FORMATS, export_registered_persona
from persona_dock.registry import RegistryService


def add_adoption_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    command = sub.add_parser("adopt", help="snapshot and adopt existing Hermes/OpenClaw personas")
    selection = command.add_mutually_exclusive_group(required=True)
    selection.add_argument("--instance", action="append", help="runtime instance ID; repeat for batch adoption")
    selection.add_argument("--all-unmanaged", action="store_true", help="adopt every currently unmanaged instance")
    command.add_argument("--id", help="Persona ID override; only valid for one instance")
    command.add_argument("--name", help="Persona display name override; only valid for one instance")
    command.add_argument("--destination", help="Persona source directory override; only valid for one instance")
    command.add_argument(
        "--link-existing",
        action="store_true",
        help="bind to an existing Persona ID without replacing its definition",
    )
    command.add_argument("--dry-run", action="store_true", help="preview adoption without snapshots or writes")
    command.add_argument("--yes", action="store_true", help="adopt without an interactive confirmation")
    command.add_argument("--json", action="store_true")

    command = sub.add_parser("export", help="export a registered persona")
    command.add_argument("persona_id")
    command.add_argument("--format", required=True, choices=sorted(EXPORT_FORMATS))
    command.add_argument("--output")
    command.add_argument(
        "--include-memory",
        action="store_true",
        help="include reviewed source memory; credentials and sessions remain excluded",
    )
    command.add_argument("--json", action="store_true")


def _adoption_instance_ids(args: argparse.Namespace, service: RegistryService) -> list[str]:
    if args.all_unmanaged:
        return [record.id for record in service.list_runtime_instances(managed=False)]
    return list(args.instance or [])


def _print_adoption_preview(values: list[dict[str, Any]]) -> None:
    for value in values:
        instance = value["instance"]
        print(f"{instance['adapter']}/{instance['platform_instance_id']} → {value['persona_id']}")
        print(f"  source: {instance['location']}")
        print(f"  destination: {value['destination']}")
        print(f"  snapshot: yes")
        print(f"  selected skill: {value.get('selected_skill') or 'none'}")
        print(f"  imported skills: {len(value.get('skills', []))}")
        print(f"  memory candidates: {len(value.get('memory_documents', []))}")
        if value.get("existing_persona"):
            print("  warning: Persona ID already exists")


def run_adoption_command(args: argparse.Namespace) -> int | None:
    if args.command == "export":
        result = export_registered_persona(
            args.persona_id,
            args.format,
            output=Path(args.output) if args.output else None,
            include_memory=args.include_memory,
        )
        value = result.to_dict()
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else result.path)
        return 0

    if args.command != "adopt":
        return None

    service = RegistryService()
    instance_ids = _adoption_instance_ids(args, service)
    if not instance_ids:
        raise ValueError("no unmanaged runtime instances are available; run `personadock discover`")
    if len(instance_ids) > 1 and any((args.id, args.name, args.destination, args.link_existing)):
        raise ValueError(
            "--id, --name, --destination, and --link-existing can only be used with one --instance"
        )

    previews = [
        adoption_preview(
            instance_id,
            persona_id=args.id,
            name=args.name,
            destination=args.destination,
            registry=service,
        )
        for instance_id in instance_ids
    ]
    if args.json and args.dry_run:
        print(json.dumps(previews, ensure_ascii=False, indent=2))
    else:
        _print_adoption_preview(previews)
    if args.dry_run:
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            raise ValueError("adoption requires --yes when standard input is not interactive")
        answer = input(f"\nAdopt {len(instance_ids)} runtime persona(s)? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Adoption cancelled.")
            return 1

    results = [
        adopt_runtime_instance(
            instance_id,
            persona_id=args.id,
            name=args.name,
            destination=args.destination,
            link_existing=args.link_existing,
            registry=service,
        ).to_dict()
        for instance_id in instance_ids
    ]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for value in results:
            print(f"Adopted {value['adapter']} instance as {value['persona_id']}: {value['destination']}")
            print(f"  snapshot: {value['snapshot']['path']}")
            print(f"  memory candidates: {value['memory_candidates']}")
    return 0
