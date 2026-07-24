from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from persona_dock import __version__
from persona_dock import session_runtime as legacy_cli
from persona_dock.adapter_registry import adapter_registry
from persona_dock.character_card import (
    CharacterCardError,
    export_character_card,
    import_character_card,
    load_character_card,
)
from persona_dock.package_trust import (
    PackageTrustError,
    generate_signing_key,
    load_trusted_key_ids,
    sign_package,
    verify_package,
)
from persona_dock.private_backup import (
    PrivateBackupError,
    create_private_backup,
    inspect_private_backup,
    restore_private_backup,
)


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("PersonaDock parser has no subcommands")


def build_parser() -> argparse.ArgumentParser:
    parser = legacy_cli.build_parser()
    parser.add_argument(
        "--version",
        action="version",
        version=f"PersonaDock {__version__}",
    )
    sub = _subparsers(parser)

    adapter = sub.add_parser("adapter", help="inspect the stable Adapter API and plugins")
    adapter_sub = adapter.add_subparsers(dest="adapter_command", required=True)
    command = adapter_sub.add_parser("list", help="list built-in and plugin Adapters")
    command.add_argument("--json", action="store_true")
    command.add_argument("--no-plugins", action="store_true")
    command = adapter_sub.add_parser("show", help="show one Adapter descriptor")
    command.add_argument("name")
    command.add_argument("--json", action="store_true")
    command.add_argument("--no-plugins", action="store_true")
    command = adapter_sub.add_parser("doctor", help="run one Adapter Doctor")
    command.add_argument("name")
    command.add_argument("--container")
    command.add_argument("--ssh-host")
    command.add_argument("--json", action="store_true")
    command.add_argument("--no-plugins", action="store_true")

    trust = sub.add_parser("trust", help="sign and verify deterministic PersonaPacks")
    trust_sub = trust.add_subparsers(dest="trust_command", required=True)
    command = trust_sub.add_parser("keygen", help="create an Ed25519 PersonaPack signing key")
    command.add_argument("private_key")
    command.add_argument("--public-key")
    command.add_argument("--force", action="store_true")
    command.add_argument("--json", action="store_true")
    command = trust_sub.add_parser("sign", help="create a detached PersonaPack signature")
    command.add_argument("package")
    command.add_argument("--key", required=True)
    command.add_argument("--output")
    command.add_argument("--json", action="store_true")
    command = trust_sub.add_parser("verify", help="verify PersonaPack integrity, compatibility, and signature")
    command.add_argument("package")
    command.add_argument("--signature")
    command.add_argument("--trusted-key", action="append", default=[])
    command.add_argument("--json", action="store_true")

    backup = sub.add_parser("backup", help="create and restore encrypted private Persona backups")
    backup_sub = backup.add_subparsers(dest="backup_command", required=True)
    command = backup_sub.add_parser("create")
    command.add_argument("project", nargs="?", default=".")
    command.add_argument("--output", required=True)
    command.add_argument("--password-env", default="PERSONADOCK_BACKUP_PASSWORD")
    command.add_argument("--json", action="store_true")
    command = backup_sub.add_parser("inspect")
    command.add_argument("backup")
    command.add_argument("--json", action="store_true")
    command = backup_sub.add_parser("restore")
    command.add_argument("backup")
    command.add_argument("destination")
    command.add_argument("--password-env", default="PERSONADOCK_BACKUP_PASSWORD")
    command.add_argument("--force", action="store_true")
    command.add_argument("--json", action="store_true")

    card = sub.add_parser("character-card", help="import and export Character Card V2/V3/CHARX")
    card_sub = card.add_subparsers(dest="card_command", required=True)
    command = card_sub.add_parser("inspect")
    command.add_argument("card")
    command.add_argument("--json", action="store_true")
    command = card_sub.add_parser("import")
    command.add_argument("card")
    command.add_argument("destination")
    command.add_argument("--id")
    command.add_argument("--locale", default="en-US")
    command.add_argument("--force", action="store_true")
    command.add_argument("--json", action="store_true")
    command = card_sub.add_parser("export")
    command.add_argument("project", nargs="?", default=".")
    command.add_argument("--output", required=True)
    command.add_argument("--card-version", type=int, choices=[2, 3], default=3)
    command.add_argument("--charx", action="store_true")
    command.add_argument("--json", action="store_true")
    return parser


def _render(value: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list, tuple)):
                print(f"{key}: {json.dumps(item, ensure_ascii=False)}")
            else:
                print(f"{key}: {item}")
    elif isinstance(value, list):
        for item in value:
            print(item)
    else:
        print(value)


def _password(environment: str, prompt: str) -> str:
    value = os.environ.get(environment)
    if value:
        return value
    if not sys.stdin.isatty():
        raise ValueError(
            f"password is required in environment variable {environment} when input is not interactive"
        )
    first = getpass.getpass(prompt)
    if not first:
        raise ValueError("password cannot be empty")
    return first


def _run_adapter(args: argparse.Namespace) -> int:
    registry = adapter_registry(load_plugins=not args.no_plugins)
    if args.adapter_command == "list":
        value = registry.summary()
        if args.json:
            _render(value, json_output=True)
        else:
            print(f"Adapter API: {value['adapter_api_version']}")
            for descriptor in value["adapters"]:
                origin = "builtin" if descriptor["builtin"] else "plugin"
                transports = ",".join(descriptor["transports"])
                print(
                    f"{descriptor['name']:<20} {origin:<8} api={descriptor['api_version']} "
                    f"transports={transports}"
                )
            for error in value["plugin_errors"]:
                print(f"Plugin warning: {error}", file=sys.stderr)
        return 0
    if args.adapter_command == "show":
        value = registry.descriptor(args.name).to_dict()
        _render(value, json_output=args.json)
        return 0
    options: dict[str, Any] = {}
    if args.container:
        options["container"] = args.container
    if args.ssh_host:
        options["ssh_host"] = args.ssh_host
    value = registry.doctor(args.name, **options)
    _render(value, json_output=args.json)
    return 0 if value["doctor"]["available"] else 1


def _run_trust(args: argparse.Namespace) -> int:
    if args.trust_command == "keygen":
        value = generate_signing_key(
            Path(args.private_key),
            public_key_path=Path(args.public_key) if args.public_key else None,
            overwrite=args.force,
        )
        _render(value, json_output=args.json)
        return 0
    if args.trust_command == "sign":
        result = sign_package(
            Path(args.package),
            Path(args.key),
            signature_path=Path(args.output) if args.output else None,
        )
        _render({"signature": str(result)}, json_output=args.json)
        return 0
    trusted = load_trusted_key_ids(Path(value) for value in args.trusted_key)
    result = verify_package(
        Path(args.package),
        signature_path=Path(args.signature) if args.signature else None,
        trusted_key_ids=trusted,
    )
    value = result.to_dict()
    _render(value, json_output=args.json)
    return 0 if result.integrity == "ok" and result.compatibility == "compatible" and result.signature != "invalid" else 1


def _run_backup(args: argparse.Namespace) -> int:
    if args.backup_command == "inspect":
        value = inspect_private_backup(Path(args.backup)).to_dict()
        _render(value, json_output=args.json)
        return 0
    password = _password(args.password_env, "Private backup password: ")
    if args.backup_command == "create":
        value = create_private_backup(
            Path(args.project),
            Path(args.output),
            password=password,
        ).to_dict()
    else:
        result = restore_private_backup(
            Path(args.backup),
            Path(args.destination),
            password=password,
            force=args.force,
        )
        value = {"restored": str(result)}
    _render(value, json_output=args.json)
    return 0


def _run_card(args: argparse.Namespace) -> int:
    if args.card_command == "inspect":
        value = load_character_card(Path(args.card)).info().to_dict()
    elif args.card_command == "import":
        result = import_character_card(
            Path(args.card),
            Path(args.destination),
            persona_id=args.id,
            locale=args.locale,
            force=args.force,
        )
        value = {"project": str(result)}
    else:
        result = export_character_card(
            Path(args.project),
            Path(args.output),
            version=args.card_version,
            charx=args.charx,
        )
        value = {"card": str(result)}
    _render(value, json_output=args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "adapter":
            return _run_adapter(args)
        if args.command == "trust":
            return _run_trust(args)
        if args.command == "backup":
            return _run_backup(args)
        if args.command == "character-card":
            return _run_card(args)
        return legacy_cli.main(argv)
    except (
        CharacterCardError,
        PackageTrustError,
        PrivateBackupError,
        FileNotFoundError,
        FileExistsError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
