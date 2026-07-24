from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from persona_dock.adapters.base import AdapterCapabilities, AdapterDoctorResult
from persona_dock.adapters.openclaw import (
    OpenClawAdapterError,
    OpenClawAgent,
    OpenClawCommandResult,
    OpenClawCommandRunner,
    parse_agents_json,
    validate_agent_id,
)
from persona_dock.io import load_jsonl, write_jsonl
from persona_dock.openclaw_cli import build_parser
from persona_dock.openclaw_deployment import (
    apply_openclaw_deployment,
    build_openclaw_overlay,
    plan_openclaw_deployment,
)
from persona_dock.openclaw_memory import (
    pull_openclaw_memory_candidates,
    push_openclaw_shared_memory,
)
from persona_dock.packaging import pack_project
from persona_dock.project import init_project
from persona_dock.registry import RegistryService
from persona_dock.registry.database import RegistryDatabase
from persona_dock.web import create_app


class FakeRunner:
    transport = "local"
    container = None
    ssh_host = None

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.fail_memory_index = False

    def run(self, arguments, *, timeout=60, check=False):
        command = list(arguments)
        self.commands.append(command)
        ok = not (
            self.fail_memory_index
            and command[:2] == ["memory", "index"]
        )
        result = OpenClawCommandResult(
            command=tuple(["openclaw", *command]),
            returncode=0 if ok else 1,
            stdout="{}" if ok else "",
            stderr="" if ok else "index failed",
        )
        if check and not ok:
            raise OpenClawAdapterError("index failed")
        return result

    def read_text(self, path: str):
        value = Path(path)
        return value.read_text(encoding="utf-8", errors="replace") if value.is_file() else None

    def write_text(self, path: str, content: str):
        value = Path(path)
        value.parent.mkdir(parents=True, exist_ok=True)
        value.write_text(content, encoding="utf-8")

    def exists(self, path: str):
        return Path(path).exists()

    def list_markdown(self, directory: str):
        value = Path(directory)
        return [str(path) for path in sorted(value.glob("*.md")) if path.is_file()] if value.is_dir() else []

    def copy_from(self, source: str, destination: str | Path):
        source_path = Path(source)
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir():
            shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
        else:
            shutil.copy2(source_path, destination_path)

    def copy_to(self, source: str | Path, destination: str):
        source_path = Path(source)
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir():
            shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
        else:
            shutil.copy2(source_path, destination_path)


class FakeOpenClawAdapter:
    def __init__(
        self,
        agents: list[OpenClawAgent] | None = None,
        runner: FakeRunner | None = None,
    ) -> None:
        self._agents = list(agents or [])
        self.runner = runner or FakeRunner()
        self.container = None
        self.ssh_host = None

    def doctor(self):
        return AdapterDoctorResult(
            adapter="openclaw",
            available=True,
            executable="openclaw",
            version="2026.7.0",
            status="ready",
            message="ready",
            capabilities=AdapterCapabilities(
                discovery=True,
                native_deployment=True,
                memory_pull=True,
                memory_push=True,
                docker=True,
            ),
            details={"native": True, "workspace_state_separation": True},
        )

    def agent(self, agent_id: str):
        return next((item for item in self._agents if item.id == agent_id), None)

    def list_agents(self):
        return list(self._agents)


def _registry(tmp_path: Path) -> RegistryService:
    return RegistryService(RegistryDatabase(tmp_path / "personadock.db"))


def _package(tmp_path: Path, persona_id: str = "xiaoyou") -> tuple[Path, Path]:
    project = init_project(
        tmp_path / f"persona-{persona_id}",
        persona_id,
        "小柚" if persona_id != "main" else "主人格",
        schema_version=3,
    )
    return project, pack_project(project)


def test_parse_agents_keeps_workspace_and_state_separate() -> None:
    agents = parse_agents_json(
        json.dumps(
            {
                "agents": [
                    {
                        "id": "main",
                        "name": "Primary",
                        "workspace": "/srv/openclaw/workspace",
                        "agentDir": "/srv/openclaw/agents/main/agent",
                        "identity": {"name": "Claw", "emoji": "🦞"},
                        "bindings": [{"channel": "telegram"}],
                    },
                    {
                        "agentId": "work",
                        "workspacePath": "/srv/openclaw/workspace-work",
                        "stateDir": "/srv/openclaw/agents/work/agent",
                    },
                ]
            }
        )
    )
    assert [item.id for item in agents] == ["main", "work"]
    assert agents[0].workspace == "/srv/openclaw/workspace"
    assert agents[0].agent_dir == "/srv/openclaw/agents/main/agent"
    assert agents[0].workspace != agents[0].agent_dir
    assert agents[0].bindings == ({"channel": "telegram"},)


def test_agent_id_and_transport_safety() -> None:
    with pytest.raises(OpenClawAdapterError, match="reserved main"):
        validate_agent_id("main", explicit_main=False)
    validate_agent_id("main", explicit_main=True)
    with pytest.raises(OpenClawAdapterError, match="must start"):
        validate_agent_id("bad agent", explicit_main=True)
    with pytest.raises(OpenClawAdapterError, match="either Docker or SSH"):
        OpenClawCommandRunner(container="claw", ssh_host="host")

    docker = OpenClawCommandRunner(
        container="claw",
        docker_executable="docker",
    )
    assert docker.command(["agents", "list", "--json"]) == [
        "docker",
        "exec",
        "claw",
        "openclaw",
        "agents",
        "list",
        "--json",
    ]
    ssh = OpenClawCommandRunner(
        ssh_host="user@example",
        ssh_executable="ssh",
    )
    assert ssh.command(["agents", "list", "--json"]) == [
        "ssh",
        "user@example",
        "openclaw",
        "agents",
        "list",
        "--json",
    ]


def test_overlay_contains_only_persona_owned_workspace_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    project, package = _package(tmp_path)
    (project / "memory" / "seed.jsonl").write_text(
        json.dumps({"id": "m", "summary": "private", "reviewed": True}) + "\n",
        encoding="utf-8",
    )
    overlay = build_openclaw_overlay(package, agent="xiaoyou")
    root = Path(overlay.path)
    assert (root / "SOUL.md").is_file()
    assert (root / "IDENTITY.md").is_file()
    assert "- Name: 小柚" in (root / "IDENTITY.md").read_text(encoding="utf-8")
    assert (root / "skills" / overlay.skill_id / "SKILL.md").is_file()
    assert (root / "personadock-manifest.json").is_file()
    for forbidden in (
        "AGENTS.md",
        "USER.md",
        "TOOLS.md",
        "MEMORY.md",
        "memory",
        "sessions",
        "auth.json",
    ):
        assert not (root / forbidden).exists()
    manifest = json.loads((root / "personadock-manifest.json").read_text(encoding="utf-8"))
    assert manifest["privacy"]["memory_included"] is False
    preserve = "\n".join(manifest["preserve"])
    for marker in ("agentDir", "auth", "sessions", "transcripts", "indexes"):
        assert marker in preserve


def test_new_agent_requires_explicit_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    _, package = _package(tmp_path)
    with pytest.raises(OpenClawAdapterError, match="explicit --workspace"):
        plan_openclaw_deployment(
            package,
            adapter=FakeOpenClawAdapter(),  # type: ignore[arg-type]
        )
    plan = plan_openclaw_deployment(
        package,
        workspace=str(tmp_path / "workspace"),
        model="openai/gpt-5.6-sol",
        bindings=["telegram:ops", "telegram:ops", "discord:guild-a"],
        adapter=FakeOpenClawAdapter(),  # type: ignore[arg-type]
    )
    assert plan.existing_agent is False
    assert plan.workspace == str((tmp_path / "workspace").resolve())
    assert plan.bindings == ("telegram:ops", "discord:guild-a")
    add = list(plan.commands[0])
    assert add[:4] == ["agents", "add", "xiaoyou", "--workspace"]
    assert "--non-interactive" in add
    assert "--model" in add
    assert add.count("--bind") == 2


def test_implicit_main_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    _, package = _package(tmp_path, "main")
    with pytest.raises(OpenClawAdapterError, match="reserved main"):
        plan_openclaw_deployment(
            package,
            workspace=str(tmp_path / "workspace-main"),
            adapter=FakeOpenClawAdapter(),  # type: ignore[arg-type]
        )


def test_unmanaged_workspace_conflicts_require_explicit_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    _, package = _package(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("existing soul", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("preserve", encoding="utf-8")
    agent = OpenClawAgent(
        id="xiaoyou",
        name="Existing",
        workspace=str(workspace),
        agent_dir=str(tmp_path / "state-dir"),
    )
    adapter = FakeOpenClawAdapter([agent])
    with pytest.raises(OpenClawAdapterError, match="unmanaged persona files"):
        plan_openclaw_deployment(
            package,
            agent="xiaoyou",
            agent_explicit=True,
            adapter=adapter,  # type: ignore[arg-type]
        )
    plan = plan_openclaw_deployment(
        package,
        agent="xiaoyou",
        agent_explicit=True,
        take_ownership=True,
        adapter=adapter,  # type: ignore[arg-type]
    )
    assert plan.conflicts == ("SOUL.md",)
    assert plan.state_directory == str(tmp_path / "state-dir")
    assert any("AGENTS.md" in item for item in plan.preserves)


def test_apply_existing_overlay_preserves_workspace_and_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    project, package = _package(tmp_path)
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "agents" / "xiaoyou" / "agent"
    state_dir.mkdir(parents=True)
    (state_dir / "sessions.json").write_text("state", encoding="utf-8")
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("agent rules", encoding="utf-8")
    (workspace / "USER.md").write_text("user data", encoding="utf-8")
    (workspace / "MEMORY.md").write_text("native memory", encoding="utf-8")
    (workspace / "SOUL.md").write_text("old soul", encoding="utf-8")
    (workspace / "personadock-manifest.json").write_text(
        json.dumps(
            {
                "format": "personadock-openclaw-workspace-overlay",
                "owned_paths": ["SOUL.md", "IDENTITY.md", "skills/xiaoyou-persona", "personadock-manifest.json"],
            }
        ),
        encoding="utf-8",
    )
    runner = FakeRunner()
    agent = OpenClawAgent(
        id="xiaoyou",
        name="Existing",
        workspace=str(workspace),
        agent_dir=str(state_dir),
        identity={"name": "Existing"},
    )
    adapter = FakeOpenClawAdapter([agent], runner)
    service = _registry(tmp_path / "registry")
    service.register_persona(
        persona_id="xiaoyou",
        name="小柚",
        version="0.1.0",
        source_path=project,
        schema_version=3,
    )
    plan = plan_openclaw_deployment(
        package,
        agent="xiaoyou",
        agent_explicit=True,
        adapter=adapter,  # type: ignore[arg-type]
    )
    result = apply_openclaw_deployment(
        plan,
        adapter=adapter,  # type: ignore[arg-type]
        registry=service,
    )
    assert result.created_agent is False
    assert result.state_directory == str(state_dir)
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == "agent rules"
    assert (workspace / "USER.md").read_text(encoding="utf-8") == "user data"
    assert (workspace / "MEMORY.md").read_text(encoding="utf-8") == "native memory"
    assert (state_dir / "sessions.json").read_text(encoding="utf-8") == "state"
    assert "# 小柚" in (workspace / "SOUL.md").read_text(encoding="utf-8")
    assert result.snapshot_path is not None
    assert service.summary()["bindings"] == 1
    binding = service.list_bindings("xiaoyou")[0]
    assert binding.last_deployed_version == "0.1.0"


def test_memory_pull_is_unreviewed_and_push_preserves_native_content(tmp_path: Path) -> None:
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
    workspace = tmp_path / "workspace"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("OpenClaw 本地长期记忆\n", encoding="utf-8")
    (workspace / "memory" / "2026-07-24.md").write_text("今日观察\n", encoding="utf-8")
    state_dir = tmp_path / "state-dir"
    state_dir.mkdir()
    runner = FakeRunner()
    adapter = FakeOpenClawAdapter(
        [OpenClawAgent("xiaoyou", "小柚", str(workspace), str(state_dir))],
        runner,
    )
    service = _registry(tmp_path / "registry")
    service.register_persona(
        persona_id="xiaoyou",
        name="小柚",
        version="0.1.0",
        source_path=project,
        schema_version=3,
    )
    first = pull_openclaw_memory_candidates(
        "xiaoyou",
        agent_id="xiaoyou",
        adapter=adapter,  # type: ignore[arg-type]
        registry=service,
    )
    second = pull_openclaw_memory_candidates(
        "xiaoyou",
        agent_id="xiaoyou",
        adapter=adapter,  # type: ignore[arg-type]
        registry=service,
    )
    candidates = load_jsonl(project / ".private" / "memory-candidates.jsonl")
    assert first["added"] == 2
    assert second["added"] == 0
    assert all(item["reviewed"] is False for item in candidates)
    assert all(item["sync_scope"] == "local-only" for item in candidates)

    result = push_openclaw_shared_memory(
        "xiaoyou",
        agent_id="xiaoyou",
        adapter=adapter,  # type: ignore[arg-type]
        registry=service,
    )
    content = (workspace / "MEMORY.md").read_text(encoding="utf-8")
    assert "OpenClaw 本地长期记忆" in content
    assert "用户喜欢咖啡" in content
    assert "不得同步" not in content
    assert "personadock-shared-memory:start" in content
    assert Path(result["backup"]).read_text(encoding="utf-8") == "OpenClaw 本地长期记忆\n"
    assert ["memory", "index", "--agent", "xiaoyou", "--force"] in runner.commands


def test_memory_index_failure_restores_original(tmp_path: Path) -> None:
    project = init_project(tmp_path / "persona", "xiaoyou", "小柚", schema_version=3)
    write_jsonl(
        project / "memory" / "seed.jsonl",
        [{"id": "m", "summary": "shared", "reviewed": True}],
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory = workspace / "MEMORY.md"
    memory.write_text("original", encoding="utf-8")
    runner = FakeRunner()
    runner.fail_memory_index = True
    adapter = FakeOpenClawAdapter(
        [OpenClawAgent("xiaoyou", "小柚", str(workspace), str(tmp_path / "state-dir"))],
        runner,
    )
    service = _registry(tmp_path / "registry")
    service.register_persona(
        persona_id="xiaoyou",
        name="小柚",
        version="0.1.0",
        source_path=project,
        schema_version=3,
    )
    with pytest.raises(OpenClawAdapterError, match="indexing failed"):
        push_openclaw_shared_memory(
            "xiaoyou",
            agent_id="xiaoyou",
            adapter=adapter,  # type: ignore[arg-type]
            registry=service,
        )
    assert memory.read_text(encoding="utf-8") == "original"


def test_cli_and_web_expose_native_openclaw_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    parser = build_parser()
    parsed = parser.parse_args(
        [
            "deploy",
            "persona.personapack",
            "--target",
            "openclaw",
            "--agent",
            "xiaoyou",
            "--workspace",
            "/srv/openclaw/workspace-xiaoyou",
            "--bind",
            "telegram:ops",
            "--take-ownership",
            "--dry-run",
        ]
    )
    assert parsed.agent == "xiaoyou"
    assert parsed.workspace == "/srv/openclaw/workspace-xiaoyou"
    assert parsed.bind == ["telegram:ops"]
    assert parsed.take_ownership is True
    rollback = parser.parse_args(
        ["openclaw", "rollback", "--agent", "xiaoyou", "--snapshot", "snapshot"]
    )
    assert rollback.openclaw_command == "rollback"

    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/openclaw" in paths
    assert "/api/openclaw/doctor" in paths
    assert "/api/openclaw/agents" in paths
    assert "/api/openclaw/plans" in paths
    assert "/api/openclaw/deployments" in paths
    assert "/api/openclaw/rollback" in paths
    assert "/api/openclaw/memory/pull" in paths
    assert "/api/openclaw/memory/push" in paths
