from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from persona_dock import openclaw_cli
from persona_dock.sync_engine import SyncEngine, SyncError
from persona_dock.sync_registry import SyncRegistry


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("PersonaDock parser has no subcommands")


def build_parser() -> argparse.ArgumentParser:
    parser = openclaw_cli.build_parser()
    sub = _subparsers(parser)

    sync = sub.add_parser("sync", help="govern cross-runtime definition and memory synchronization")
    sync_sub = sync.add_subparsers(dest="sync_command", required=True)

    policy = sync_sub.add_parser("policy", help="show or update a Persona SyncPolicy")
    policy_sub = policy.add_subparsers(dest="sync_policy_command", required=True)
    command = policy_sub.add_parser("show")
    command.add_argument("persona_id")
    command.add_argument("--json", action="store_true")
    command = policy_sub.add_parser("set")
    command.add_argument("persona_id")
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", help="YAML or JSON policy file")
    source.add_argument("--config-json", help="inline JSON policy patch")
    command.add_argument("--replace", action="store_true")
    command.add_argument("--json", action="store_true")

    command = sync_sub.add_parser("collect", help="pull bound runtime memory into the review queue")
    command.add_argument("persona_id")
    command.add_argument("--json", action="store_true")

    command = sync_sub.add_parser("candidates", help="list governed memory items")
    command.add_argument("persona_id")
    command.add_argument("--status", choices=["pending", "approved", "rejected", "superseded"])
    command.add_argument("--sensitivity", choices=["public", "internal", "private", "restricted"])
    command.add_argument("--source-adapter", choices=["hermes", "openclaw"])
    command.add_argument("--json", action="store_true")

    review = sync_sub.add_parser("review", help="approve, reject, or resolve memory review items")
    review_sub = review.add_subparsers(dest="sync_review_command", required=True)
    command = review_sub.add_parser("approve")
    command.add_argument("item_id")
    command.add_argument("--reviewer", default="user")
    command.add_argument("--scope", choices=["local-only", "shared"])
    command.add_argument("--json", action="store_true")
    command = review_sub.add_parser("reject")
    command.add_argument("item_id")
    command.add_argument("--reviewer", default="user")
    command.add_argument("--reason")
    command.add_argument("--json", action="store_true")
    command = review_sub.add_parser("resolve")
    command.add_argument("conflict_id")
    command.add_argument(
        "--resolution",
        required=True,
        choices=["keep-existing", "replace", "keep-both"],
    )
    command.add_argument("--reviewer", default="user")
    command.add_argument("--json", action="store_true")

    command = sync_sub.add_parser("conflicts", help="list unresolved or resolved conflicts")
    command.add_argument("persona_id")
    command.add_argument("--status", choices=["pending", "resolved"])
    command.add_argument("--json", action="store_true")

    command = sync_sub.add_parser("plan", help="preview definition and memory propagation")
    command.add_argument("persona_id")
    command.add_argument("--json", action="store_true")

    command = sync_sub.add_parser("apply", help="apply a freshly generated governed sync plan")
    command.add_argument("persona_id")
    command.add_argument(
        "--definitions",
        action="store_true",
        help="also deploy out-of-date Canonical Persona definitions",
    )
    command.add_argument("--yes", action="store_true")
    command.add_argument("--json", action="store_true")

    command = sync_sub.add_parser("status", help="show policy, queue, conflicts, runs, and propagation")
    command.add_argument("persona_id")
    command.add_argument("--json", action="store_true")

    return parser


def _load_policy(args: argparse.Namespace) -> dict[str, Any]:
    if args.config_json:
        value = json.loads(args.config_json)
    else:
        path = Path(args.file).expanduser().resolve()
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("sync policy input must contain an object")
    return value


def _print_policy(value: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(value, allow_unicode=True, sort_keys=False))


def _print_items(values: list[dict[str, Any]]) -> None:
    if not values:
        print("No memory items found.")
        return
    for value in values:
        print(
            f"{value['id']}  {value['status']:<10} {value['sensitivity']:<10} "
            f"{value['memory_type']:<16} {value['summary'][:90]}"
        )
        source = value.get("source_adapter") or "canonical"
        print(f"  source: {source}  scope: {value['sync_scope']}  key: {value['memory_key']}")


def _print_plan(value: dict[str, Any]) -> None:
    print(f"Persona: {value['persona_id']}")
    print(f"Policy mode: {value['policy']['mode']}")
    print(f"Definition actions: {len(value['definition_actions'])}")
    print(f"Memory actions: {len(value['memory_actions'])}")
    print(f"Conflicts: {len(value['conflicts'])}")
    print(f"Skipped: {len(value['skipped'])}")
    if value["definition_actions"]:
        print("\nDefinition push:")
        for action in value["definition_actions"]:
            print(
                f"- {action['adapter']}/{action['platform_instance_id']}: "
                f"{action.get('current_version') or 'not deployed'} -> {action['target_version']}"
            )
    if value["memory_actions"]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for action in value["memory_actions"]:
            grouped.setdefault(action["runtime_instance_id"], []).append(action)
        print("\nMemory push:")
        for actions in grouped.values():
            first = actions[0]
            print(
                f"- {first['adapter']}/{first['platform_instance_id']}: "
                f"{len(actions)} reviewed item(s)"
            )
    if value["conflicts"]:
        print("\nBlocked conflicts:")
        for conflict in value["conflicts"]:
            print(f"- {conflict['id']} {conflict['conflict_type']}")
    for warning in value["warnings"]:
        print(f"Warning: {warning}")


def _confirm(yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise ValueError("sync apply requires --yes when standard input is not interactive")
    return input("Apply this governed sync plan? [y/N] ").strip().lower() in {"y", "yes"}


def _run_sync(args: argparse.Namespace) -> int:
    engine = SyncEngine()
    registry = engine.sync
    if args.sync_command == "policy":
        if args.sync_policy_command == "show":
            value = registry.get_policy(args.persona_id).to_dict()
        else:
            value = registry.set_policy(
                args.persona_id,
                _load_policy(args),
                replace=args.replace,
            ).to_dict()
        _print_policy(value, args.json)
        return 0
    if args.sync_command == "collect":
        value = engine.collect(args.persona_id)
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value)
        return 0
    if args.sync_command == "candidates":
        values = [
            item.to_dict()
            for item in registry.list_memory_items(
                args.persona_id,
                status=args.status,
                sensitivity=args.sensitivity,
                source_adapter=args.source_adapter,
            )
        ]
        if args.json:
            print(json.dumps(values, ensure_ascii=False, indent=2))
        else:
            _print_items(values)
        return 0
    if args.sync_command == "review":
        if args.sync_review_command == "approve":
            value = engine.approve(
                args.item_id,
                reviewer=args.reviewer,
                sync_scope=args.scope,
            ).to_dict()
        elif args.sync_review_command == "reject":
            value = engine.reject(
                args.item_id,
                reviewer=args.reviewer,
                reason=args.reason,
            ).to_dict()
        else:
            value = engine.resolve_conflict(
                args.conflict_id,
                args.resolution,
                reviewer=args.reviewer,
            )
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value)
        return 0
    if args.sync_command == "conflicts":
        values = [
            conflict.to_dict()
            for conflict in registry.list_conflicts(args.persona_id, status=args.status)
        ]
        print(json.dumps(values, ensure_ascii=False, indent=2) if args.json else values)
        return 0
    if args.sync_command == "plan":
        value = engine.plan(args.persona_id).to_dict()
        if args.json:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            _print_plan(value)
        return 0
    if args.sync_command == "apply":
        plan = engine.plan(args.persona_id)
        if args.json:
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        else:
            _print_plan(plan.to_dict())
        if not _confirm(args.yes):
            print("Synchronization cancelled.")
            return 1
        value = engine.apply(plan, include_definitions=args.definitions)
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value)
        return 0 if value["status"] == "success" else 1
    if args.sync_command == "status":
        value = engine.dashboard(args.persona_id)
        if args.json:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            print(f"Persona: {args.persona_id}")
            print(f"Policy: {value['policy']['config']['mode']}")
            for key, count in value["counts"].items():
                print(f"{key}: {count}")
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            return _run_sync(args)
        return openclaw_cli.main(argv)
    except (SyncError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
