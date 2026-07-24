from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from persona_dock.adoption import AdoptionError, adopt_runtime_instance, adoption_preview
from persona_dock.exports import export_registered_persona
from persona_dock.registry.database import RegistryDatabase
from persona_dock.registry.service import RegistryService
from persona_dock.web import create_app


def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RegistryService:
    state = tmp_path / "state"
    monkeypatch.setenv("PERSONADOCK_HOME", str(state))
    return RegistryService(RegistryDatabase(state / "personadock.db"))


def add_instance(
    registry: RegistryService,
    root: Path,
    *,
    adapter: str,
    instance_id: str = "xiaoyou",
):
    return registry.upsert_runtime_instance(
        adapter=adapter,
        transport="local",
        platform_instance_id=instance_id,
        display_name="小柚",
        location=str(root),
        capabilities={"read_only_discovery": True},
        metadata={"discovery_source": "test"},
    )


def make_hermes(root: Path) -> None:
    (root / "skills" / "xiaoyou-persona" / "references").mkdir(parents=True)
    (root / "memories").mkdir()
    (root / "sessions" / "session-1").mkdir(parents=True)
    (root / "SOUL.md").write_text("# 小柚\n\n嘴硬心软，难过时先倾听。\n", encoding="utf-8")
    (root / "config.yaml").write_text("model: test\n", encoding="utf-8")
    (root / ".env").write_text("SECRET_TOKEN=never-copy\n", encoding="utf-8")
    (root / "sessions" / "session-1" / "messages.json").write_text("[]", encoding="utf-8")
    (root / "skills" / "xiaoyou-persona" / "SKILL.md").write_text(
        "---\nname: xiaoyou-persona\ndescription: 小柚人格\n---\n\n# 小柚 Skill\n",
        encoding="utf-8",
    )
    (root / "skills" / "xiaoyou-persona" / "references" / "voice.md").write_text(
        "# Voice\n\n短句。\n", encoding="utf-8"
    )
    (root / "memories" / "MEMORY.md").write_text(
        "# Memory\n\n用户喜欢先看结论。\n", encoding="utf-8"
    )
    (root / "memories" / "USER.md").write_text(
        "# User\n\n用户的项目叫 PersonaDock。\n", encoding="utf-8"
    )


def make_openclaw(root: Path) -> None:
    (root / "skills" / "xiaoyou-persona").mkdir(parents=True)
    (root / "memory").mkdir()
    (root / "SOUL.md").write_text("# 小柚\n\nOpenClaw 人格。\n", encoding="utf-8")
    (root / "IDENTITY.md").write_text("# 小柚\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Existing agent rules\n", encoding="utf-8")
    (root / "TOOLS.md").write_text("# Existing tools\n", encoding="utf-8")
    (root / "MEMORY.md").write_text("# Memory\n\n共享候选。\n", encoding="utf-8")
    (root / "memory" / "2026-07-24.md").write_text("# Daily\n\n当天经历。\n", encoding="utf-8")
    (root / "skills" / "xiaoyou-persona" / "SKILL.md").write_text(
        "---\nname: xiaoyou-persona\ndescription: 小柚人格\n---\n\n# Skill\n",
        encoding="utf-8",
    )


def test_adoption_preview_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = service(tmp_path, monkeypatch)
    runtime = tmp_path / "hermes"
    make_hermes(runtime)
    instance = add_instance(registry, runtime, adapter="hermes")
    before = (runtime / "SOUL.md").read_bytes()

    preview = adoption_preview(instance.id, registry=registry)

    assert preview["persona_id"] == "xiaoyou"
    assert preview["selected_skill"] == "xiaoyou-persona"
    assert preview["will_snapshot"] is True
    assert len(preview["memory_documents"]) == 2
    assert registry.summary()["snapshots"] == 0
    assert (runtime / "SOUL.md").read_bytes() == before


def test_adoption_snapshots_and_binds_without_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = service(tmp_path, monkeypatch)
    runtime = tmp_path / "hermes"
    make_hermes(runtime)
    instance = add_instance(registry, runtime, adapter="hermes")

    result = adopt_runtime_instance(instance.id, registry=registry)

    project = Path(result.destination)
    snapshot = Path(result.snapshot.path)
    assert (project / "companion.yaml").is_file()
    assert (project / "skills/persona/SKILL.md").is_file()
    assert (project / ".private/imported-skills/xiaoyou-persona/SKILL.md").is_file()
    assert (project / ".private/adoption.json").is_file()
    candidates = (project / ".private/memory-candidates.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(candidates) == 2
    assert all(json.loads(line)["reviewed"] is False for line in candidates)
    assert all(json.loads(line)["sync_scope"] == "local-only" for line in candidates)

    assert (snapshot / "content/SOUL.md").is_file()
    assert (snapshot / "content/config.yaml").is_file()
    assert not (snapshot / "content/.env").exists()
    assert not (snapshot / "content/sessions").exists()
    manifest = json.loads((snapshot / "snapshot-manifest.json").read_text(encoding="utf-8"))
    assert ".env" in manifest["never_included"]
    assert "sessions" in manifest["never_included"]

    assert registry.summary()["personas"] == 1
    assert registry.summary()["managed_instances"] == 1
    assert registry.summary()["bindings"] == 1
    assert registry.summary()["snapshots"] == 1
    assert registry.list_bindings("xiaoyou")[0].adopted is True

    assert (runtime / ".env").read_text(encoding="utf-8") == "SECRET_TOKEN=never-copy\n"
    assert (runtime / "sessions/session-1/messages.json").read_text(encoding="utf-8") == "[]"


def test_existing_persona_requires_explicit_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = service(tmp_path, monkeypatch)
    runtime = tmp_path / "hermes"
    make_hermes(runtime)
    instance = add_instance(registry, runtime, adapter="hermes")
    source = tmp_path / "existing"
    source.mkdir()
    registry.register_persona(
        persona_id="xiaoyou",
        name="已有小柚",
        version="1.0.0",
        source_path=source,
        schema_version=2,
    )

    with pytest.raises(AdoptionError, match="already exists"):
        adopt_runtime_instance(instance.id, registry=registry)


def test_native_exports_exclude_runtime_state_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = service(tmp_path, monkeypatch)
    runtime = tmp_path / "openclaw"
    make_openclaw(runtime)
    instance = add_instance(registry, runtime, adapter="openclaw")
    adopt_runtime_instance(instance.id, registry=registry)

    persona_pack = export_registered_persona("xiaoyou", "personapack", registry=registry)
    hermes = export_registered_persona("xiaoyou", "hermes-profile", registry=registry)
    openclaw = export_registered_persona("xiaoyou", "openclaw-workspace", registry=registry)

    assert Path(persona_pack.path).is_file()
    with zipfile.ZipFile(hermes.path) as archive:
        names = set(archive.namelist())
        assert "distribution.yaml" in names
        assert "SOUL.md" in names
        assert not any(name.startswith("memory/") for name in names)
        assert not any("session" in name.lower() for name in names)
        assert not any(name.endswith(".env") for name in names)
    with zipfile.ZipFile(openclaw.path) as archive:
        names = set(archive.namelist())
        assert "personadock-manifest.json" in names
        assert "SOUL.md" in names
        assert "AGENTS.md" not in names
        assert "TOOLS.md" not in names
        assert "MEMORY.md" not in names
        assert not any(name.startswith("memory/") for name in names)


def test_phase_two_web_routes_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/adoptions/preview" in paths
    assert "/api/adoptions" in paths
    assert "/api/personas/{persona_id}/exports" in paths
    assert "/api/exports/download" in paths
