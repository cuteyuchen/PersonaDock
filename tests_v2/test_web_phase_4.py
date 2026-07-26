from __future__ import annotations

import base64
from importlib.resources import files
from pathlib import Path

import pytest

from persona_dock.application import (
    ArtifactApplicationService,
    ArtifactPathError,
    ArtifactStore,
    PersonaApplicationService,
)
from persona_dock.registry import RegistryService
from persona_dock.registry.database import RegistryDatabase
from persona_dock.web import create_app
from persona_dock.web.version import WEB_REFACTOR_PHASE


def _services(tmp_path: Path) -> tuple[ArtifactApplicationService, Path]:
    registry = RegistryService(RegistryDatabase(tmp_path / "registry.db"))
    created = PersonaApplicationService(registry).create(
        tmp_path / "personas" / "xiaoyou",
        persona_id="xiaoyou",
        name="小柚",
        locale="zh-CN",
    )
    return (
        ArtifactApplicationService(
            registry,
            ArtifactStore(tmp_path / "artifacts"),
        ),
        Path(created["project"]),
    )


def test_artifact_store_upload_and_path_confinement(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    uploaded = store.upload_base64(
        "../unsafe name.json",
        base64.b64encode(b'{"ok":true}').decode("ascii"),
    )
    assert uploaded.parent == store.roots.uploads
    assert uploaded.name == "unsafe-name.json"
    assert store.resolve(uploaded, categories=("uploads",)) == uploaded

    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactPathError, match="outside"):
        store.resolve(outside)
    with pytest.raises(ArtifactPathError, match="16 MiB"):
        store.upload("large.bin", b"x" * (ArtifactStore.MAX_UPLOAD_BYTES + 1))


def test_build_pack_sign_and_verify_workflow(tmp_path: Path) -> None:
    service, _ = _services(tmp_path)

    build = service.build("xiaoyou", targets=["hermes", "openclaw"])
    assert Path(build["archive"]).is_file()
    assert "targets/hermes/SOUL.md" in build["files"]
    assert "targets/openclaw/SOUL.md" in build["files"]

    packed = service.pack("xiaoyou", targets=["hermes", "openclaw"])
    package = Path(packed["path"])
    assert package.is_file()
    assert packed["manifest"]["integrity"] == "ok"
    assert packed["manifest"]["integrity_errors"] == []

    key = service.create_key("release")
    assert "private_key" not in key
    assert Path(key["public_key"]).is_file()
    signature = service.sign(package, key_id=key["key_id"])
    assert Path(signature["signature"]).is_file()

    verified = service.verify(
        package,
        signature_path=signature["signature"],
        trust_local_keys=True,
    )
    assert verified["integrity"] == "ok"
    assert verified["compatibility"] == "compatible"
    assert verified["signature"] == "valid-trusted"
    assert verified["trusted"] is True


def test_private_backup_and_character_card_workflows(tmp_path: Path) -> None:
    service, _ = _services(tmp_path)

    backup = service.create_backup("xiaoyou", password="correct horse battery staple")
    backup_path = Path(backup["path"])
    assert backup_path.is_file()
    inspected = service.inspect_backup(backup_path)
    assert inspected["format"] == "personadock-private-backup"
    assert inspected["persona_id"] == "xiaoyou"

    restored = service.restore_backup(
        backup_path,
        tmp_path / "personas" / "xiaoyou-restored",
        password="correct horse battery staple",
    )
    assert Path(restored["restored"]).is_dir()
    assert restored["persona"]["id"] == "xiaoyou"

    exported = service.export_character_card("xiaoyou", version=3, charx=False)
    card_path = Path(exported["path"])
    assert card_path.is_file()
    card = service.inspect_character_card(card_path)
    assert card["spec"] == "chara_card_v3"
    assert card["spec_version"] == "3.0"
    imported = service.import_character_card(
        card_path,
        tmp_path / "personas" / "xiaoyou-card",
        persona_id="xiaoyou-card",
        locale="zh-CN",
    )
    assert imported["persona"]["id"] == "xiaoyou-card"


def test_adapter_and_skill_plans_use_existing_contracts(tmp_path: Path) -> None:
    service, project = _services(tmp_path)
    summary = service.adapter_summary()
    names = {item["name"] for item in summary["adapters"]}
    assert {"hermes", "openclaw"}.issubset(names)
    assert service.adapter("hermes")["builtin"] is True

    plan = service.skill_plan("codex", scope="project", project_root=project)
    assert plan["target"] == "codex"
    assert plan["scope"] == "project"
    assert Path(plan["destination"]).is_relative_to(project)


def test_phase_four_routes_and_assets_are_registered() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    for path in (
        "/api/v1/artifacts",
        "/api/v1/uploads",
        "/api/v1/artifacts/download",
        "/api/v1/personas/{persona_id}/builds",
        "/api/v1/personas/{persona_id}/packages",
        "/api/v1/personas/{persona_id}/public-export",
        "/api/v1/packages/inspect",
        "/api/v1/trust/keys",
        "/api/v1/trust/signatures",
        "/api/v1/trust/verify",
        "/api/v1/personas/{persona_id}/backups",
        "/api/v1/backups/inspect",
        "/api/v1/backups/restore",
        "/api/v1/character-cards/inspect",
        "/api/v1/character-cards/import",
        "/api/v1/personas/{persona_id}/character-card",
        "/api/v1/adapters",
        "/api/v1/adapters/{adapter_name}/doctor",
        "/api/v1/skills/plan",
        "/api/v1/skills/install",
    ):
        assert path in paths
    assert WEB_REFACTOR_PHASE >= 4


def test_phase_four_never_places_passwords_or_private_keys_in_web_state() -> None:
    root = files("persona_dock")
    html = root.joinpath("web/static/index.html").read_text(encoding="utf-8")
    css = root.joinpath("web/static/artifacts.css").read_text(encoding="utf-8")
    javascript = root.joinpath("web/static/artifacts.js").read_text(encoding="utf-8")
    api_source = root.joinpath("web/artifact_api.py").read_text(encoding="utf-8")

    assert 'href="/assets/artifacts.css"' in html
    assert 'src="/assets/artifacts.js"' in html
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert "16 MiB" in javascript
    assert "private signing keys cannot be downloaded" in api_source
    assert 'input={"persona_id": persona_id}' in api_source
    assert '"password": request.password' not in api_source
    assert "sessionStorage" not in api_source
