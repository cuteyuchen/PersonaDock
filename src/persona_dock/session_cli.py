from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from persona_dock import sync_cli
from persona_dock.session_engine import SessionSummaryEngine, SessionSummaryError


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("PersonaDock parser has no subcommands")


def build_parser() -> argparse.ArgumentParser:
    parser = sync_cli.build_parser()
    sub = _subparsers(parser)
    session = sub.add_parser(
        "session",
        help="collect, review, preview, and propagate Session Summaries",
    )
    session_sub = session.add_subparsers(dest="session_command", required=True)

    policy = session_sub.add_parser("policy", help="show or update Session Summary policy")
    policy_sub = policy.add_subparsers(dest="session_policy_command", required=True)
    command = policy_sub.add_parser("show")
    command.add_argument("persona_id")
    command.add_argument("--json", action="store_true")
    command = policy_sub.add_parser("set")
    command.add_argument("persona_id")
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--file")
    source.add_argument("--config-json")
    command.add_argument("--replace", action="store_true")
    command.add_argument("--json", action="store_true")

    command = session_sub.add_parser("collect", help="collect summary drafts from bound runtimes")
    command.add_argument("persona_id")
    command.add_argument("--json", action="store_true")

    command = session_sub.add_parser("list", help="list Session Summary review records")
    command.add_argument("persona_id")
    command.add_argument("--status", choices=["pending", "approved", "rejected", "superseded"])
    command.add_argument("--source-adapter", choices=["hermes", "openclaw", "manual"])
    command.add_argument("--sensitivity", choices=["public", "internal", "private", "restricted"])
    command.add_argument("--json", action="store_true")

    command = session_sub.add_parser("add", help="add a manual Session Summary draft")
    command.add_argument("persona_id")
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--summary")
    source.add_argument("--summary-file")
    command.add_argument("--title", default="Manual summary")
    command.add_argument("--task", action="append", default=[])
    command.add_argument("--emotion-label")
    command.add_argument("--emotion-note")
    command.add_argument(
        "--sensitivity",
        choices=["public", "internal", "private", "restricted"],
        default="internal",
    )
    command.add_argument("--json", action="store_true")

    review = session_sub.add_parser("review", help="approve or reject Session Summary drafts")
    review_sub = review.add_subparsers(dest="session_review_command", required=True)
    command = review_sub.add_parser("approve")
    command.add_argument("summary_id")
    command.add_argument("--reviewer", default="user")
    command.add_argument("--scope", choices=["local-only", "shared"], default="shared")
    command.add_argument("--json", action="store_true")
    command = review_sub.add_parser("reject")
    command.add_argument("summary_id")
    command.add_argument("--reviewer", default="user")
    command.add_argument("--reason")
    command.add_argument("--json", action="store_true")

    command = session_sub.add_parser("plan", help="preview reviewed summary propagation")
    command.add_argument("persona_id")
    command.add_argument("--json", action="store_true")

    command = session_sub.add_parser("apply", help="propagate a freshly generated summary plan")
    command.add_argument("persona_id")
    command.add_argument("--yes", action="store_true")
    command.add_argument("--json", action="store_true")

    command = session_sub.add_parser(
        "preview",
        help="experimental redacted preview of one raw Session or Transcript",
    )
    command.add_argument("persona_id")
    command.add_argument("runtime_instance_id")
    command.add_argument("session_id")
    command.add_argument("--experimental", action="store_true")
    command.add_argument("--json", action="store_true")

    command = session_sub.add_parser("status", help="show policy, review queue, and propagation")
    command.add_argument("persona_id")
    command.add_argument("--json", action="store_true")
    return parser


def _load_object(args: argparse.Namespace) -> dict[str, Any]:
    if args.config_json:
        value = json.loads(args.config_json)
    else:
        path = Path(args.file).expanduser().resolve()
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Session Summary policy input must contain an object")
    return value


def _summary_text(args: argparse.Namespace) -> str:
    if args.summary is not None:
        return args.summary
    return Path(args.summary_file).expanduser().resolve().read_text(encoding="utf-8")


def _print_summaries(values: list[dict[str, Any]]) -> None:
    if not values:
        print("No Session Summaries found.")
        return
    for value in values:
        print(
            f"{value['id']}  {value['status']:<10} {value['sensitivity']:<10} "
            f"{value['source_adapter']:<10} {value['source_title'][:70]}"
        )
        print(f"  {value['summary'][:120]}")
        if value["pending_tasks"]:
            print(f"  pending: {len(value['pending_tasks'])}")


def _print_plan(value: dict[str, Any]) -> None:
    print(f"Persona: {value['persona_id']}")
    print(f"Policy: {value['policy']['mode']}")
    print(f"Destination actions: {len(value['actions'])}")
    print(f"Skipped: {len(value['skipped'])}")
    for action in value["actions"]:
        print(
            f"- {action['adapter']}/{action['platform_instance_id']}: "
            f"{len(action['summaries'])} reviewed summary item(s)"
        )
    for warning in value["warnings"]:
        print(f"Warning: {warning}")


def _confirm(yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise ValueError("session apply requires --yes when standard input is not interactive")
    return input("Propagate reviewed Session Summaries? [y/N] ").strip().lower() in {"y", "yes"}


def _run_session(args: argparse.Namespace) -> int:
    engine = SessionSummaryEngine()
    registry = engine.session
    if args.session_command == "policy":
        if args.session_policy_command == "show":
            value = registry.get_policy(args.persona_id).to_dict()
        else:
            value = registry.set_policy(
                args.persona_id,
                _load_object(args),
                replace=args.replace,
            ).to_dict()
        print(
            json.dumps(value, ensure_ascii=False, indent=2)
            if args.json
            else yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
        )
        return 0
    if args.session_command == "collect":
        value = engine.collect(args.persona_id)
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value)
        return 0
    if args.session_command == "list":
        values = [
            item.to_dict()
            for item in registry.list_summaries(
                args.persona_id,
                status=args.status,
                source_adapter=args.source_adapter,
                sensitivity=args.sensitivity,
            )
        ]
        if args.json:
            print(json.dumps(values, ensure_ascii=False, indent=2))
        else:
            _print_summaries(values)
        return 0
    if args.session_command == "add":
        emotional = {
            key: value
            for key, value in {
                "label": args.emotion_label,
                "note": args.emotion_note,
            }.items()
            if value
        }
        value = engine.add_manual(
            args.persona_id,
            summary=_summary_text(args),
            title=args.title,
            pending_tasks=args.task,
            emotional_context=emotional,
            sensitivity=args.sensitivity,
        ).to_dict()
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value)
        return 0
    if args.session_command == "review":
        if args.session_review_command == "approve":
            value = engine.approve(
                args.summary_id,
                reviewer=args.reviewer,
                sync_scope=args.scope,
            ).to_dict()
        else:
            value = engine.reject(
                args.summary_id,
                reviewer=args.reviewer,
                reason=args.reason,
            ).to_dict()
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value)
        return 0
    if args.session_command == "plan":
        value = engine.plan(args.persona_id).to_dict()
        if args.json:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            _print_plan(value)
        return 0
    if args.session_command == "apply":
        plan = engine.plan(args.persona_id)
        if args.json:
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        else:
            _print_plan(plan.to_dict())
        if not _confirm(args.yes):
            print("Session Summary propagation cancelled.")
            return 1
        value = engine.apply(plan)
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value)
        return 0 if value["status"] == "success" else 1
    if args.session_command == "preview":
        value = engine.raw_preview(
            args.persona_id,
            args.runtime_instance_id,
            args.session_id,
            confirmed_experimental=args.experimental,
        )
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else value)
        return 0
    if args.session_command == "status":
        value = engine.dashboard(args.persona_id)
        if args.json:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            print(f"Persona: {args.persona_id}")
            print(f"Policy: {value['policy']['config']['mode']}")
            for key, count in value["counts"].items():
                print(f"{key}: {count}")
            print(f"Propagation records: {len(value['propagation'])}")
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "session":
            return _run_session(args)
        return sync_cli.main(argv)
    except (
        SessionSummaryError,
        ValueError,
        OSError,
        json.JSONDecodeError,
        yaml.YAMLError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
