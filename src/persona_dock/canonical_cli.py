from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from persona_dock import cli as legacy_cli
from persona_dock.application import PersonaApplicationService
from persona_dock.core.diff import diff_personas
from persona_dock.core.migration import migrate_project_to_v3
from persona_dock.core.testing import run_persona_tests


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("PersonaDock parser has no subcommands")


def build_parser() -> argparse.ArgumentParser:
    parser = legacy_cli.build_parser()
    sub = _subparsers(parser)

    command = sub.add_parser("migrate", help="migrate a PersonaDock v2 project to Canonical Persona v3")
    command.add_argument("project", nargs="?", default=".")
    destination = command.add_mutually_exclusive_group()
    destination.add_argument("--in-place", action="store_true")
    destination.add_argument("--output")
    command.add_argument("--no-backup", action="store_true")
    command.add_argument("--json", action="store_true")

    command = sub.add_parser("diff", help="show semantic differences between two v3 personas")
    command.add_argument("before")
    command.add_argument("after")
    command.add_argument("--json", action="store_true")

    command = sub.add_parser("test", help="run Canonical Persona scenario and quality tests")
    command.add_argument("project", nargs="?", default=".")
    command.add_argument("--json", action="store_true")

    return parser


def _run_init(args: argparse.Namespace) -> int:
    result = PersonaApplicationService().create(
        Path(args.destination),
        persona_id=args.id,
        name=args.name,
        locale=args.locale,
        force=args.force,
    )
    print(result["project"])
    return 0


def _run_migrate(args: argparse.Namespace) -> int:
    result = migrate_project_to_v3(
        Path(args.project),
        output=Path(args.output) if args.output else None,
        in_place=args.in_place,
        backup=not args.no_backup,
    )
    if result.changed:
        PersonaApplicationService().register(Path(result.project))
    value = result.to_dict()
    if args.json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(f"Migrated schema {result.from_schema} → {result.to_schema}: {result.project}")
        if result.backup:
            print(f"Backup: {result.backup}")
        print(f"Behaviors: {result.behavior_rules}; boundaries: {result.boundaries}")
    return 0


def _run_diff(args: argparse.Namespace) -> int:
    report = diff_personas(Path(args.before), Path(args.after))
    value = report.to_dict()
    if args.json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    print(f"Changed: {'yes' if report.changed else 'no'}")
    for label, values in [
        ("Added behaviors", report.added_behaviors),
        ("Removed behaviors", report.removed_behaviors),
        ("Changed behaviors", report.changed_behaviors),
        ("Added boundaries", report.added_boundaries),
        ("Removed boundaries", report.removed_boundaries),
        ("Changed boundaries", report.changed_boundaries),
    ]:
        if values:
            print(f"{label}: {', '.join(values)}")
    for change in report.field_changes:
        print(f"Field {change.path}: {change.before!r} → {change.after!r}")
    return 0


def _run_tests(args: argparse.Namespace) -> int:
    report = run_persona_tests(Path(args.project))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        for result in report.results:
            state = "PASS" if result.passed else "FAIL"
            print(f"{state} {result.id}: {result.message}")
        print(f"\nPassed: {report.passed}; failed: {report.failed}")
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return _run_init(args)
    if args.command == "migrate":
        return _run_migrate(args)
    if args.command == "diff":
        return _run_diff(args)
    if args.command == "test":
        return _run_tests(args)
    return legacy_cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
