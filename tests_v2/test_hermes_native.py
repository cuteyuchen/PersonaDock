from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from persona_dock.adapters.base import AdapterCapabilities, AdapterDoctorResult
from persona_dock.adapters.hermes import (
    HermesAdapterError,
    HermesCommandRunner,
    HermesProfile,
    parse_profile_names,
    validate_profile_name,
)
from persona_dock.hermes_cli import build_parser
from persona_dock.hermes_deployment import (
    build_hermes_distribution,
    plan_hermes_deployment,
)
from persona_dock.hermes_memory import (
    pull_hermes_memory_candidates,
    push_hermes_shared_memory,
)
from persona_dock.io import load_jsonl, write_jsonl
from persona_dock.packaging import pack_project
from persona_dock.project import init_project
from persona_dock.registry import RegistryService
from persona_dock.registry.database import RegistryDatabase
from persona_dock.web import create_app


class FakeHermesAdapter:
    def __init__(
        self,
        profile: HermesProfile | None = None,
        *,
        container: str | None = None,
    ) -> None:
        self._profile = profile
        self.container = container

    def doctor(self) -> AdapterDoctorResult:
        return AdapterDoctorResult(
            adapter="hermes",
            available=True,
            executable="hermes",
            version="0.12.1",
            status="ready",
            message="ready",
            capabilities=AdapterCapabilities(
                discovery=True,
                native_deployment=True,
                memory_pull=True,
                memory_push=True,
                docker=True,
            ),
            details={"native": True},
        )

    def profile(self, name: str) -> HermesProfile | None:
        if self._profile and self._profile.name == name:
            return self._profile
        return None


def _registry(tmp_path: Path) -> RegistryService:
    return RegistryService(RegistryDatabase(tmp_path / "personadock.db"))


def test_profile_parser_and_name_safety() -> None:
    output = """
    Profiles
    --------
    * default | Default profile
      xiaoyou | Managed profile
    """
    assert parse_profile_names(output) == [("default", True), ("xiaoyou", False)]

    with pytest.raises(HermesAdapterError, match="default Hermes profile"):
        validate_profile_name("default", explicit_default=False)
    validate_profile_name("default", explicit_default=True)
    with pytest.raises(HermesAdapterError, match="reserves"):
        validate_profile_name("hermes", explicit_default=True)
    with pytest.raises(HermesAdapterError, match="must start"):
        validate_profile_name("bad profile", explicit_default=True)


def test_docker_command_generation_is_native() -> None:
    runner = HermesCommandRunner(
        executable="ignored",
        container="hermes-box",
        docker_executable="docker",
    )
    assert runner.command(["profile", "list"]) == [
        "docker",
        "exec",
        "hermes-box",
        "hermes",
        "profile",
        "list",
    ]


def test_distribution_contains_only_owned_definition_files(tmp_path: Path) -> None:
    project = init_project(
        tmp_path / "persona",
        "xiaoyou",
        "小柚",
        schema_version=3,
    )
    (project / ".env").write_text("SECRET=1", encoding="utf-8")
    (project / "memory" / "seed.jsonl").write_text(
        json.dumps({"id": "m1", "summary": "private", "reviewed": True}) + "\n",
        encoding="utf-8",
    )
    package = pack_project(project)

    artifact = build_hermes_distribution(package, profile="xiaoyou")
    root = Path(artifact.path)
    assert (root / "SOUL.md").is_file()
    assert (root / "distribution.yaml").is_file()
    assert (root / "personadock-manifest.json").is_file()
    assert any(path.name == "SKILL.md" for path in (root / "skills").rglob("SKILL.md"))
    assert not (root / "memory").exists()
    assert not (root / "memories").exists()
    assert not (root / ".env").exists()
    assert not (root / "sessions").exists()
    manifest = json.loads((root / "personadock-manifest.json").read_text(encoding="utf-8"))
    assert "memories/" in manifest["excluded"]
    assert "sessions/" in manifest["excluded"]
    assert ".env" in manifest["excluded"]


def test_existing_profile_plan_snapshots_updates_and_activates(tmp_path: Path) -> None:
    project = init_project(
        tmp_path / "persona",
        "xiaoyou",
        "小柚",
        schema_version=3,
    )
    package = pack_project(project)
    fake = FakeHermesAdapter(
        HermesProfile(
            name="xiaoyou",
            active=False,
            path=str(tmp_path / "profile"),
            distribution={"version": "0.0.9"},
        )
    )

    plan = plan_hermes_deployment(
        package,
        profile="xiaoyou",
        profile_explicit=True,
        activate=True,
        alias=True,
        adapter=fake,  # type: ignore[arg-type]
    )
    commands = [list(command) for command in plan.commands]
    assert plan.existing_profile is True
    assert plan.snapshot_path is not None
    assert commands[0][:3] == ["profile", "export", "xiaoyou"]
    install = next(command for command in commands if command[:2] == ["profile", "install"])
    assert "--force" in install
    assert "--alias" in install
    assert ["profile", "use", "xiaoyou"] in commands
    assert any("memories" in item.lower() for item in plan.preserves)
    assert any("sessions" in item.lower() for item in plan.preserves)


def test_implicit_default_profile_is_rejected(tmp_path: Path) -> None:
    project = init_project(
        tmp_path / "persona",
        "default",
        "默认人格",
        schema_version=3,
    )
    package = pack_project(project)
    with pytest.raises(HermesAdapterError, match="default Hermes profile"):
        plan_hermes_deployment(
            package,
            adapter=FakeHermesAdapter(),  # type: ignore[arg-type]
        )


def test_memory_pull_creates_unreviewed_candidates_idempotently(tmp_path: Path) -> None:
    project = init_project(
        tmp_path / "persona",
        "xiaoyou",
        "小柚",
        schema_version=3,
    )
    profile_root = tmp_path / "profile"
    (profile_root / "memories").mkdir(parents=True)
    (profile_root / "memories" / "MEMORY.md").write_text(
        "喜欢咖啡\n§\n正在开发 PersonaDock\n",
        encoding="utf-8",
    )
    service = _registry(tmp_path / "registry")
    service.register_persona(
        persona_id="xiaoyou",
        name="小柚",
        version="0.1.0",
        source_path=project,
        schema_version=3,
    )
    adapter = FakeHermesAdapter(
        HermesProfile("xiaoyou", False, str(profile_root))
    )

    first = pull_hermes_memory_candidates(
        "xiaoyou",
        profile="xiaoyou",
        adapter=adapter,  # type: ignore[arg-type]
        registry=service,
    )
    second = pull_hermes_memory_candidates(
        "xiaoyou",
        profile="xiaoyou",
        adapter=adapter,  # type: ignore[arg-type]
        registry=service,
    )
    records = load_jsonl(project / ".private" / "memory-candidates.jsonl")
    assert first["added"] == 2
    assert second["added"] == 0
    assert len(records) == 2
    assert all(record["reviewed"] is False for record in records)
    assert all(record["sync_scope"] == "local-only" for record in records)


def test_memory_push_preserves_native_content_and_creates_backup(tmp_path: Path) -> None:
    project = init_project(
        tmp_path / "persona",
        "xiaoyou",
        "小柚",
        schema_version=3,
    )
    write_jsonl(
        project / "memory" / "seed.jsonl",
        [
            {"id": "reviewed", "summary": "用户喜欢咖啡", "reviewed": True},
            {"id": "pending", "summary": "不得同步", "reviewed": False},
        ],
    )
    profile_root = tmp_path / "profile"
    (profile_root / "memories").mkdir(parents=True)
    memory_file = profile_root / "memories" / "MEMORY.md"
    memory_file.write_text("Hermes 本地记忆\n", encoding="utf-8")
    service = _registry(tmp_path / "registry")
    service.register_persona(
        persona_id="xiaoyou",
        name="小柚",
        version="0.1.0",
        source_path=project,
        schema_version=3,
    )
    adapter = FakeHermesAdapter(
        HermesProfile("xiaoyou", False, str(profile_root))
    )

    result = push_hermes_shared_memory(
        "xiaoyou",
        profile="xiaoyou",
        adapter=adapter,  # type: ignore[arg-type]
        registry=service,
    )
    content = memory_file.read_text(encoding="utf-8")
    assert "Hermes 本地记忆" in content
    assert "用户喜欢咖啡" in content
    assert "不得同步" not in content
    assert "personadock-shared-memory:start" in content
    assert Path(result["backup"]).read_text(encoding="utf-8") == "Hermes 本地记忆\n"
    assert service.summary()["snapshots"] == 1


def test_cli_and_web_expose_native_hermes_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    parser = build_parser()
    parsed = parser.parse_args(
        [
            "deploy",
            "persona.personapack",
            "--target",
            "hermes",
            "--profile",
            "xiaoyou",
            "--activate",
            "--dry-run",
        ]
    )
    assert parsed.profile == "xiaoyou"
    assert parsed.activate is True
    assert parsed.legacy_filesystem is False
    rollback = parser.parse_args(
        ["hermes", "rollback", "--profile", "xiaoyou", "--snapshot", "backup.tar.gz"]
    )
    assert rollback.hermes_command == "rollback"

    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/hermes" in paths
    assert "/api/hermes/doctor" in paths
    assert "/api/hermes/profiles" in paths
    assert "/api/hermes/plans" in paths
    assert "/api/hermes/deployments" in paths
    assert "/api/hermes/rollback" in paths
    assert "/api/hermes/memory/pull" in paths
    assert "/api/hermes/memory/push" in paths
