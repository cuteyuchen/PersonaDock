from __future__ import annotations

import base64
import json
import shutil
import struct
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from persona_dock import __version__
from persona_dock.adapter_registry import AdapterRegistry, adapter_registry
from persona_dock.adapters.base import (
    ADAPTER_API_VERSION,
    AdapterCapabilities,
    AdapterDoctorResult,
    PersonaAdapter,
)
from persona_dock.character_card import (
    export_character_card,
    import_character_card,
    load_character_card,
)
from persona_dock.package_trust import (
    generate_signing_key,
    sign_package,
    verify_package,
)
from persona_dock.packaging import inspect_package, pack_project
from persona_dock.private_backup import (
    FORMAT_VERSION as PRIVATE_BACKUP_FORMAT_VERSION,
)
from persona_dock.private_backup import (
    PrivateBackupError,
    create_private_backup,
    inspect_private_backup,
    restore_private_backup,
)
from persona_dock.project import PROJECT_FILE, init_project, validate_project
from persona_dock.registry.database import SCHEMA_VERSION as REGISTRY_SCHEMA_VERSION
from persona_dock.stable_cli import build_parser


GOLDEN = Path(__file__).parent / "golden" / "v1-contracts.json"


def _project(tmp_path: Path) -> Path:
    project = init_project(
        tmp_path / "persona",
        "golden-persona",
        "Golden Persona",
        locale="en-US",
        schema_version=3,
    )
    (project / ".private/raw/private.txt").write_text(
        "private project evidence", encoding="utf-8"
    )
    return project


def test_golden_v1_contracts_are_stable() -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    registry = adapter_registry(load_plugins=False)
    descriptors = {item.name: item for item in registry.descriptors()}
    actual = {
        "adapter_api_version": ADAPTER_API_VERSION,
        "adapters": {
            name: {"transports": list(descriptors[name].transports)}
            for name in sorted(descriptors)
        },
        "canonical_schema_version": 3,
        "character_card_versions": ["2.0", "3.0"],
        "personapack_format_version": 2,
        "private_backup_format_version": PRIVATE_BACKUP_FORMAT_VERSION,
        "registry_schema_version": REGISTRY_SCHEMA_VERSION,
    }
    assert actual == expected
    assert __version__.split(".", 1)[0] == "1"
    assert descriptors["hermes"].capabilities.session_summary_pull is True
    assert descriptors["openclaw"].capabilities.raw_session_import is True


class IncompatibleAdapter(PersonaAdapter):
    name = "future"
    api_version = "2.0"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities()

    def doctor(self) -> AdapterDoctorResult:
        return AdapterDoctorResult(
            adapter=self.name,
            available=True,
            executable=None,
            version=None,
            status="ready",
            message="test",
            capabilities=self.capabilities,
        )

    def plan_deployment(
        self,
        package: str,
        *,
        destination: str | None = None,
        container: str | None = None,
    ) -> dict:
        return {"package": package}


class PluginAdapter(IncompatibleAdapter):
    name = "plugin"
    api_version = "1.0"


class EntryPoints(list):
    def select(self, *, group: str):
        return self


def test_adapter_registry_rejects_incompatible_plugins_and_loads_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from persona_dock import adapter_registry as module

    entries = EntryPoints(
        [
            SimpleNamespace(
                name="plugin",
                group="personadock.adapters",
                load=lambda: PluginAdapter,
                dist=SimpleNamespace(name="plugin-package"),
            ),
            SimpleNamespace(
                name="future",
                group="personadock.adapters",
                load=lambda: IncompatibleAdapter,
                dist=SimpleNamespace(name="future-package"),
            ),
        ]
    )
    monkeypatch.setattr(module.importlib_metadata, "entry_points", lambda: entries)
    registry = AdapterRegistry(load_plugins=True)
    assert "plugin" in registry.names()
    assert "future" not in registry.names()
    assert registry.descriptor("plugin").builtin is False
    assert any(item["entry_point"] == "future" for item in registry.plugin_errors)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("hermes", PluginAdapter)


def test_personapack_is_deterministic_and_has_1x_trust_metadata(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = pack_project(project, tmp_path / "first.personapack")
    second = pack_project(project, tmp_path / "second.personapack")
    assert first.read_bytes() == second.read_bytes()
    info = inspect_package(first)
    assert info["integrity"] == "ok"
    assert info["compatibility"] == {
        "adapter_api": "1.x",
        "canonical_schema": "3",
        "minimum_personadock": "1.0.0",
        "personapack": "2.x",
    }
    assert info["trust"]["signature_scheme"] == "detached-ed25519-v1"
    assert info["ownership"]["runtime_sessions_included"] is False


def test_personapack_signature_trust_and_tampering(tmp_path: Path) -> None:
    package = pack_project(_project(tmp_path), tmp_path / "persona.personapack")
    keys = generate_signing_key(tmp_path / "signing.pem")
    signature = sign_package(package, Path(keys["private_key"]))
    trusted = verify_package(
        package,
        signature_path=signature,
        trusted_key_ids={keys["key_id"]},
    )
    assert trusted.integrity == "ok"
    assert trusted.compatibility == "compatible"
    assert trusted.signature == "valid-trusted"
    assert trusted.trusted is True

    tampered = tmp_path / "tampered.personapack"
    tampered.write_bytes(package.read_bytes() + b"tamper")
    invalid = verify_package(
        tampered,
        signature_path=signature,
        trusted_key_ids={keys["key_id"]},
    )
    assert invalid.signature == "invalid"
    assert invalid.trusted is False


def test_personapack_rejects_unexpected_archive_members(tmp_path: Path) -> None:
    package = pack_project(_project(tmp_path), tmp_path / "persona.personapack")
    with zipfile.ZipFile(package, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("unexpected.txt", "not declared")
    info = inspect_package(package)
    assert info["integrity"] == "failed"
    assert "unexpected file: unexpected.txt" in info["integrity_errors"]


def test_private_backup_round_trip_wrong_password_and_tamper(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "dist").mkdir()
    (project / "dist/ignored.txt").write_text("ignore", encoding="utf-8")
    backup = tmp_path / "persona.pdbackup"
    info = create_private_backup(project, backup, password="correct horse battery staple")
    inspected = inspect_private_backup(backup)
    assert info.archive_sha256 == inspected.archive_sha256
    assert inspected.includes_private_project_data is True
    assert inspected.excludes_runtime_state is True

    restored = restore_private_backup(
        backup,
        tmp_path / "restored",
        password="correct horse battery staple",
    )
    assert (restored / PROJECT_FILE).is_file()
    assert (restored / ".private/raw/private.txt").read_text(encoding="utf-8") == "private project evidence"
    assert not (restored / "dist/ignored.txt").exists()

    with pytest.raises(PrivateBackupError, match="authentication failed"):
        restore_private_backup(
            backup,
            tmp_path / "wrong",
            password="wrong password",
        )

    modified = tmp_path / "modified.pdbackup"
    payload = bytearray(backup.read_bytes())
    payload[-1] ^= 1
    modified.write_bytes(payload)
    with pytest.raises(PrivateBackupError, match="authentication failed"):
        restore_private_backup(
            modified,
            tmp_path / "modified-restore",
            password="correct horse battery staple",
        )


def _card_payload() -> dict:
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": "Rin",
            "description": "Rin is a careful technical companion.",
            "personality": "careful, concise, honest",
            "scenario": "The user is debugging a deployment.",
            "first_mes": "What failed?",
            "mes_example": "<START>\n{{user}}: It broke.\n{{char}}: Show me the error.",
            "creator_notes": "Imported test card.",
            "system_prompt": "Be precise and never invent command output.",
            "post_history_instructions": "Prefer actionable steps.",
            "alternate_greetings": ["Ready to debug?"],
            "tags": ["technical"],
            "creator": "tester",
            "character_version": "2.4",
            "extensions": {"unknown_vendor": {"keep": True}},
        },
    }


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def test_character_card_json_png_and_charx_round_trip(tmp_path: Path) -> None:
    payload = _card_payload()
    card = tmp_path / "rin.json"
    card.write_text(json.dumps(payload), encoding="utf-8")
    project = import_character_card(card, tmp_path / "rin-project", persona_id="rin")
    assert validate_project(project) == []
    preserved = json.loads(
        (project / ".private/imports/character-card.json").read_text(encoding="utf-8")
    )
    assert preserved["data"]["extensions"]["unknown_vendor"]["keep"] is True

    exported = export_character_card(
        project,
        tmp_path / "rin-v3.json",
        version=3,
    )
    document = load_character_card(exported)
    assert document.spec == "chara_card_v3"
    assert document.data["extensions"]["unknown_vendor"]["keep"] is True
    assert document.data["extensions"]["personadock"]["memory_included"] is False

    charx = export_character_card(
        project,
        tmp_path / "rin.charx",
        version=3,
        charx=True,
    )
    assert load_character_card(charx).container == "charx"

    encoded = base64.b64encode(json.dumps(payload).encode("utf-8"))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"tEXt", b"chara\x00" + encoded)
        + _png_chunk(b"IEND", b"")
    )
    png_path = tmp_path / "rin.png"
    png_path.write_bytes(png)
    assert load_character_card(png_path).data["name"] == "Rin"


def test_stable_cli_exposes_1x_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["adapter", "list"]).command == "adapter"
    assert parser.parse_args(["trust", "verify", "x.personapack"]).command == "trust"
    assert parser.parse_args(["backup", "inspect", "x.pdbackup"]).command == "backup"
    assert parser.parse_args(["character-card", "inspect", "x.json"]).command == "character-card"
    assert parser.parse_args(["session", "status", "persona"]).command == "session"
