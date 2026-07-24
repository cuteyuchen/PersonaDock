from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from persona_dock.discovery import discover_hermes, discover_openclaw, discover_runtime_instances
from persona_dock.project import init_project
from persona_dock.registry.database import SCHEMA_VERSION, RegistryDatabase
from persona_dock.registry.service import RegistryService
from persona_dock.web import create_app


def registry(tmp_path: Path) -> RegistryService:
    return RegistryService(RegistryDatabase(tmp_path / "personadock.db"))


def test_registry_initialization_is_repeatable(tmp_path: Path) -> None:
    database = RegistryDatabase(tmp_path / "personadock.db")
    database.initialize()
    database.initialize()
    assert database.schema_version() == SCHEMA_VERSION == 2

    service = RegistryService(database)
    assert service.summary() == {
        "schema_version": 2,
        "personas": 0,
        "instances": 0,
        "managed_instances": 0,
        "bindings": 0,
        "snapshots": 0,
        "journal_events": 0,
    }


def test_persona_registration_is_idempotent(tmp_path: Path) -> None:
    service = registry(tmp_path)
    project = init_project(tmp_path / "persona", "persona", "测试人格")

    first = service.register_persona(
        persona_id="persona",
        name="测试人格",
        version="0.1.0",
        source_path=project,
        schema_version=2,
        summary="初始摘要",
    )
    second = service.register_persona(
        persona_id="persona",
        name="更新的人格名",
        version="0.2.0",
        source_path=project,
        schema_version=2,
        summary="更新摘要",
    )

    assert first.id == second.id == "persona"
    assert len(service.list_personas()) == 1
    assert service.get_persona("persona").version == "0.2.0"  # type: ignore[union-attr]


def test_runtime_instance_upsert_is_idempotent(tmp_path: Path) -> None:
    service = registry(tmp_path)
    values = {
        "adapter": "hermes",
        "transport": "local",
        "platform_instance_id": "xiaoyou",
        "display_name": "小柚",
        "location": str(tmp_path / "hermes"),
        "capabilities": {"native_profile": True},
        "metadata": {"discovery_source": "test"},
    }

    first = service.upsert_runtime_instance(**values)
    second = service.upsert_runtime_instance(**{**values, "display_name": "小柚更新"})

    assert first.id == second.id
    instances = service.list_runtime_instances()
    assert len(instances) == 1
    assert instances[0].display_name == "小柚更新"


def test_hermes_filesystem_discovery_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import persona_dock.discovery as discovery

    home = tmp_path / "home"
    hermes = home / ".hermes"
    profile = hermes / "profiles" / "xiaoyou"
    profile.mkdir(parents=True)
    soul = profile / "SOUL.md"
    soul.write_text("# 小柚\n\n原内容\n", encoding="utf-8")
    (profile / "skills" / "persona").mkdir(parents=True)

    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(discovery.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(discovery.shutil, "which", lambda _: None)

    values, warnings = discover_hermes()

    assert warnings == []
    assert len(values) == 1
    assert values[0].platform_instance_id == "xiaoyou"
    assert values[0].display_name == "小柚"
    assert values[0].metadata["skill_count"] == 1
    assert soul.read_text(encoding="utf-8") == "# 小柚\n\n原内容\n"


def test_hermes_cli_discovery_parses_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import persona_dock.discovery as discovery

    profile = tmp_path / "profiles" / "coder"
    profile.mkdir(parents=True)
    (profile / "SOUL.md").write_text("# Coder\n", encoding="utf-8")

    monkeypatch.setattr(discovery.shutil, "which", lambda name: "/usr/bin/hermes" if name == "hermes" else None)

    def fake_run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        if arguments[-1] == "list":
            return subprocess.CompletedProcess(arguments, 0, "  default\n* coder\n", "")
        name = arguments[-1]
        path = profile if name == "coder" else tmp_path / "default"
        return subprocess.CompletedProcess(arguments, 0, f"Profile: {name}\nPath: {path}\n", "")

    monkeypatch.setattr(discovery, "_run", fake_run)
    values, _ = discover_hermes()

    assert [value.platform_instance_id for value in values] == ["coder", "default"]
    coder = next(value for value in values if value.platform_instance_id == "coder")
    assert coder.metadata["active"] is True
    assert coder.capabilities["native_profile"] is True


def test_openclaw_json_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import persona_dock.discovery as discovery

    workspace = tmp_path / "workspace-xiaoyou"
    workspace.mkdir()
    (workspace / "IDENTITY.md").write_text("# 小柚\n", encoding="utf-8")
    (workspace / "SOUL.md").write_text("# 小柚人格\n", encoding="utf-8")

    monkeypatch.setattr(discovery.shutil, "which", lambda name: "/usr/bin/openclaw" if name == "openclaw" else None)
    payload = {
        "agents": [
            {
                "id": "xiaoyou",
                "workspace": str(workspace),
                "identity": {"name": "小柚"},
            }
        ]
    }
    monkeypatch.setattr(
        discovery,
        "_run",
        lambda arguments: subprocess.CompletedProcess(arguments, 0, json.dumps(payload), ""),
    )

    values, warnings = discover_openclaw()

    assert warnings == []
    assert len(values) == 1
    assert values[0].platform_instance_id == "xiaoyou"
    assert values[0].display_name == "小柚"
    assert values[0].metadata["files"] == ["SOUL.md", "IDENTITY.md"]


def test_discovery_persists_without_duplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import persona_dock.discovery as discovery

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("# Main\n", encoding="utf-8")
    discovered = discovery.DiscoveredInstance(
        adapter="openclaw",
        transport="local",
        platform_instance_id="main",
        display_name="Main",
        location=str(workspace),
        capabilities={"read_only_discovery": True},
        metadata={"discovery_source": "test"},
    )
    monkeypatch.setattr(discovery, "discover_hermes", lambda: ([], []))
    monkeypatch.setattr(discovery, "discover_openclaw", lambda: ([discovered], []))
    service = registry(tmp_path)

    first = discover_runtime_instances(registry=service)
    second = discover_runtime_instances(registry=service)

    assert len(first.instances) == len(second.instances) == 1
    assert first.instances[0].id == second.instances[0].id
    assert len(service.list_runtime_instances()) == 1
    assert service.summary()["journal_events"] == 2


def test_phase_one_web_routes_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/registry" in paths
    assert "/api/personas" in paths
    assert "/api/personas/{persona_id}" in paths
    assert "/api/instances" in paths
    assert "/api/instances/{instance_id}" in paths
    assert "/api/discover" in paths
