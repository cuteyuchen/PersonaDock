from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from persona_dock import sync_cli
from persona_dock.session_engine import SessionSummaryEngine, SessionSummaryError


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("PersonaDock parser has no subcommands")


def build_parser() -> argparse.ArgumentParser:
    parser = sync_cli.build_parser()
    root = _subparsers(parser)
    sessions = root.add_parser(
        "sessions",
        help="preview, review, and synchronize sanitized session summaries",
    )
    sub = sessions.add_subparsers(dest="sessions_command", required=True)

    command = sub.add_parser("preview", help="preview a raw JSON/JSONL export without persisting it")
    command.add_argument("file", type=Path)
    command.add_argument("--session-id")
    command.add_argument("--max-turns", type=int, default=20)
    command.add_argument("--include-emotional-context", action="store_true")
    command.add_argument("--json", action="store_true")

    command = sub.add_parser("import", help="create reviewed-later summaries from a local export")
    command.add_argument("persona_id")
    command.add_argument("file", type=Path)
    command.add_argument(
        "--source-adapter",
        choices=["file", "hermes", "openclaw"],
        default="file",
    )
    command.add_argument("--instance", dest="runtime_instance_id")
    command.add_argument("--session-id")
    command.add_argument("--json", action="store_true")

    command = sub.add_parser("collect", help="use a bound runtime's native read-only export command")
    command.add_argument("persona_id")
    command.add_argument("--instance", required=True, dest="runtime_instance_id")
    command.add_argument("--session-id", required=True, dest="session_identifier")
    command.add_argument("--json", action="store_true")

    command = sub.add_parser("list", help="list session summary review records")
    command.add_argument("persona_id")
    command.add_argument(
        "--status",
        choices=["pending", "approved", "rejected", "superseded"],
    )
    command.add_argument("--source-adapter", choices=["file", "hermes", "openclaw"])
    command.add_argument("--json", action="store_true")

    review = sub.add_parser("review", help="approve or reject a session summary")
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

    command = sub.add_parser("status", help="show summary policy and review queue")
    command.add_argument("persona_id")
    command.add_argument("--json", action="store_true")
    return parser


def _print_summary(value: dict) -> None:
    print(
        f"{value['id']}  {value['status']:<9} {value['sensitivity']:<10} "
        f"{value['source_adapter']:<9} {value['source_title'] or value['source_session_id']}"
    )
    print(value["summary"][:240].replace("\n", " "))
    if value.get("pending_tasks"):
        print(f"  pending tasks: {len(value['pending_tasks'])}")
    if value.get("decisions"):
        print(f"  decisions: {len(value['decisions'])}")


def _run_sessions(args: argparse.Namespace) -> int:
    engine = SessionSummaryEngine()
    if args.sessions_command == "preview":
        value = engine.preview_file(
            args.file,
            session_id=args.session_id,
            max_turns=args.max_turns,
            include_emotional_context=args.include_emotional_context,
        )
    elif args.sessions_command == "import":
        value = engine.import_file(
            args.persona_id,
            args.file,
            source_adapter=args.source_adapter,
            runtime_instance_id=args.runtime_instance_id,
            session_id=args.session_id,
        )
    elif args.sessions_command == "collect":
        value = engine.collect_native(
            args.persona_id,
            args.runtime_instance_id,
            args.session_identifier,
        )
    elif args.sessions_command == "list":
        values = [
            item.to_dict()
            for item in engine.sessions.list(
                args.persona_id,
                status=args.status,
                source_adapter=args.source_adapter,
            )
        ]
        if args.json:
            print(json.dumps(values, ensure_ascii=False, indent=2))
        else:
            if not values:
                print("No session summaries found.")
            for value in values:
                _print_summary(value)
        return 0
    elif args.sessions_command == "review":
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
    elif args.sessions_command == "status":
        value = engine.dashboard(args.persona_id)
    else:
        return 2

    if getattr(args, "json", False):
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(value)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "sessions":
            return _run_sessions(args)
        return sync_cli.main(argv)
    except (SessionSummaryError, ValueError, FileNotFoundError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
