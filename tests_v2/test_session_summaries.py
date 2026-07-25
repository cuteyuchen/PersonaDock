from __future__ import annotations

import json
from pathlib import Path

import pytest

from persona_dock.project import init_project
from persona_dock.registry.database import RegistryDatabase, SCHEMA_VERSION
from persona_dock.registry.service import RegistryService
from persona_dock.session_cli import build_parser
from persona_dock.session_engine import SessionSummaryEngine
from persona_dock.session_models import build_session_summary, parse_session_export
from persona_dock.sync_engine import SyncEngine
from persona_dock.sync_registry import SyncRegistry
from persona_dock.web import create_app


def _service(tmp_path: Path) -> tuple[RegistryService, Path]:
    project = init_project(tmp_path / "persona", "xiaoyou", "小柚", schema_version=3)
    service = RegistryService(RegistryDatabase(tmp_path / "personadock.db"))
    service.register_persona(
        persona_id="xiaoyou",
        name="小柚",
        version="0.1.0",
        source_path=project,
        schema_version=3,
    )
    return service, project


def _export(path: Path, *, secret: bool = True) -> Path:
    key = "sk-abcdefghijklmnop" if secret else "普通内容"
    payload = {
        "id": "session-001",
        "title": "PersonaDock Web 重构",
        "source": "cli",
        "started_at": "2026-07-24T10:00:00Z",
        "updated_at": "2026-07-24T10:30:00Z",
        "messages": [
            {"role": "system", "content": "internal system prompt"},
            {"role": "user", "content": f"我有些焦虑。API key={key}。决定使用本地 Web 控制台。"},
            {"role": "assistant", "content": "已确认采用 FastAPI。下一步需要完成会话摘要审核页。"},
            {"role": "tool", "content": "tool secret output"},
            {"role": "user", "content": "待办：测试 Windows 独立程序。"},
            {"role": "assistant", "content": "好的，后续运行五平台打包验证。"},
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _instance(
    service: RegistryService,
    *,
    adapter: str,
    platform_id: str,
    location: Path,
):
    value = service.upsert_runtime_instance(
        adapter=adapter,
        transport="local",
        platform_instance_id=platform_id,
        display_name=platform_id,
        location=str(location),
        capabilities={
            "memory_pull": True,
            "memory_push": True,
            "session_summary_pull": True,
            "raw_session_import": True,
        },
        metadata={},
    )
    service.bind("xiaoyou", value.id, adopted=True)
    return value


def test_parser_filters_system_tools_and_redacts_secrets(tmp_path: Path) -> None:
    document = parse_session_export(_export(tmp_path / "session.jsonl"))[0]
    assert document.session_id == "session-001"
    assert [message.role for message in document.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert all("system prompt" not in message.content for message in document.messages)
    assert all("tool secret" not in message.content for message in document.messages)
    assert all("sk-abcdefghijklmnop" not in message.content for message in document.messages)
    assert any("[REDACTED" in message.content for message in document.messages)
    assert document.detected_sensitivity == "restricted"

    default = build_session_summary(document)
    assert default.emotional_context == ()
    assert default.pending_tasks
    assert default.decisions
    opted_in = build_session_summary(document, include_emotional_context=True)
    assert "anxious" in opted_in.emotional_context


def test_import_is_review_first_and_never_persists_raw_transcript(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    source = _export(tmp_path / "session.jsonl")
    engine = SessionSummaryEngine(service)
    first = engine.import_file("xiaoyou", source)
    second = engine.import_file("xiaoyou", source)
    assert first["created"] == 1
    assert first["auto_approved"] == 0
    assert first["raw_persisted"] is False
    assert second["duplicates"] == 1
    item = engine.sessions.list("xiaoyou")[0]
    assert item.status == "pending"
    assert item.sync_scope == "local-only"
    assert item.memory_item_id is None
    with service.database.session() as connection:
        row = connection.execute("SELECT * FROM session_imports").fetchone()
    assert row is not None
    assert row["raw_persisted"] == 0
    assert Path(row["source_reference"]).name == source.name


def test_approved_summary_uses_existing_memory_sync_and_skips_source(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    hermes = _instance(
        service,
        adapter="hermes",
        platform_id="xiaoyou",
        location=tmp_path / "hermes",
    )
    openclaw = _instance(
        service,
        adapter="openclaw",
        platform_id="xiaoyou",
        location=tmp_path / "openclaw",
    )
    engine = SessionSummaryEngine(service)
    result = engine.import_file(
        "xiaoyou",
        _export(tmp_path / "session.jsonl", secret=False),
        source_adapter="hermes",
        runtime_instance_id=hermes.id,
    )
    approved = engine.approve(result["summary_ids"][0], reviewer="tester")
    assert approved.status == "approved"
    assert approved.sync_scope == "shared"
    assert approved.memory_item_id

    plan = SyncEngine(service).plan("xiaoyou")
    actions = [
        value
        for value in plan.memory_actions
        if value["memory_item_id"] == approved.memory_item_id
    ]
    assert [value["runtime_instance_id"] for value in actions] == [openclaw.id]
    assert any(
        value.get("runtime_instance_id") == hermes.id
        and value.get("reason") == "source echo disabled"
        for value in plan.skipped
    )


def test_automatic_summary_approval_requires_explicit_safe_policy(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    sync = SyncRegistry(service)
    sync.set_policy(
        "xiaoyou",
        {
            "session_summaries": {
                "mode": "automatic",
                "source_adapters": ["file"],
                "auto_approve": True,
                "max_sensitivity": "internal",
            }
        },
    )
    engine = SessionSummaryEngine(service)
    result = engine.import_file(
        "xiaoyou",
        _export(tmp_path / "safe.jsonl", secret=False),
    )
    assert result["auto_approved"] == 1
    assert engine.sessions.list("xiaoyou")[0].status == "approved"

    restricted = engine.import_file(
        "xiaoyou",
        _export(tmp_path / "restricted.jsonl", secret=True),
    )
    assert restricted["auto_approved"] == 0
    assert any(item.status == "pending" for item in engine.sessions.list("xiaoyou"))


def test_registry_v2_migrates_to_v3_without_losing_persona(tmp_path: Path) -> None:
    database = RegistryDatabase(tmp_path / "personadock.db")
    database.initialize()
    service = RegistryService(database)
    project = init_project(tmp_path / "old", "old", "旧人格")
    service.register_persona(
        persona_id="old",
        name="旧人格",
        version="0.1.0",
        source_path=project,
        schema_version=2,
    )
    with database.session() as connection:
        connection.execute(
            "UPDATE registry_meta SET value = '2' WHERE key = 'schema_version'"
        )
        connection.execute("DROP TABLE session_imports")
        connection.execute("DROP TABLE session_summaries")
    database.initialize()
    assert database.schema_version() == SCHEMA_VERSION == 3
    assert service.get_persona("old") is not None
    with database.session() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"session_summaries", "session_imports"} <= tables


def test_session_cli_and_web_routes_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = build_parser()
    args = parser.parse_args(["sessions", "preview", "example.jsonl"])
    assert args.command == "sessions"
    assert args.sessions_command == "preview"

    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/sessions" in paths
    assert "/api/sessions/preview" in paths
    assert "/api/sessions/{persona_id}" in paths
    assert "/api/sessions/{persona_id}/collect" in paths
    assert "/api/sessions/summaries/{summary_id}/approve" in paths
