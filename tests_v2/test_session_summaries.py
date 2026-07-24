from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from persona_dock.adapters.hermes import HermesAdapter
from persona_dock.adapters.openclaw import OpenClawAdapter
from persona_dock.io import load_jsonl
from persona_dock.project import init_project
from persona_dock.registry import RegistryService
from persona_dock.registry.database import RegistryDatabase
from persona_dock.session_engine import SessionSummaryError
from persona_dock.session_models import DEFAULT_SESSION_POLICY
from persona_dock.session_runtime import SessionSummaryEngine, build_parser
from persona_dock.session_sources import (
    OpenClawSessionSource,
    SessionSummaryDraft,
    deterministic_summary,
    extract_safe_messages,
)
from persona_dock.web import create_app


def _service(tmp_path: Path) -> RegistryService:
    return RegistryService(RegistryDatabase(tmp_path / "personadock.db"))


def _persona(
    tmp_path: Path,
    *,
    persona_id: str = "xiaoyou",
) -> tuple[Path, RegistryService, SessionSummaryEngine]:
    project = init_project(
        tmp_path / "persona",
        persona_id,
        "小柚",
        schema_version=3,
    )
    service = _service(tmp_path / "registry")
    service.register_persona(
        persona_id=persona_id,
        name="小柚",
        version="0.1.0",
        source_path=project,
        schema_version=3,
        summary="测试人格",
    )
    return project, service, SessionSummaryEngine(service)


def _runtime(
    service: RegistryService,
    *,
    adapter: str,
    platform_id: str,
    location: str,
    transport: str = "local",
    metadata: dict | None = None,
):
    return service.upsert_runtime_instance(
        adapter=adapter,
        transport=transport,
        platform_instance_id=platform_id,
        display_name=platform_id,
        location=location,
        capabilities={
            "memory_push": True,
            "session_summary_pull": True,
            "raw_session_import": True,
        },
        metadata=metadata or {"discovery_source": "test"},
    )


def test_registry_v2_migrates_to_v3_without_losing_persona(tmp_path: Path) -> None:
    path = tmp_path / "personadock.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE registry_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO registry_meta(key, value) VALUES('schema_version', '2');
        CREATE TABLE personas(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
          source_path TEXT, schema_version INTEGER NOT NULL,
          summary TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        INSERT INTO personas VALUES(
          'legacy', 'Legacy', '0.1.0', NULL, 3, '',
          '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
        );
        """
    )
    connection.commit()
    connection.close()

    database = RegistryDatabase(path)
    database.initialize()
    assert database.schema_version() == 3
    with database.session() as migrated:
        assert migrated.execute("SELECT name FROM personas WHERE id='legacy'").fetchone()[0] == "Legacy"
        tables = {
            row[0]
            for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {
        "session_summary_policies",
        "session_summaries",
        "session_summary_propagation",
    } <= tables


def test_default_policy_is_review_first_and_raw_preview_off(tmp_path: Path) -> None:
    _, _, engine = _persona(tmp_path)
    policy = engine.session.get_policy("xiaoyou").config
    assert policy == DEFAULT_SESSION_POLICY
    assert policy["mode"] == "review"
    assert policy["auto_approve"]["enabled"] is False
    assert policy["raw_preview"]["enabled"] is False


def test_safe_message_filter_excludes_system_tools_and_redacts_secrets() -> None:
    payload = {
        "messages": [
            {"role": "system", "content": "internal prompt"},
            {"role": "user", "content": "password=abc123 please follow up tomorrow"},
            {"role": "tool", "content": "tool output"},
            {"role": "assistant", "content": "I will help."},
            {"role": "reasoning", "content": "hidden chain"},
        ]
    }
    messages = extract_safe_messages(payload, max_messages=10, max_chars=2000)
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert "abc123" not in messages[0]["content"]
    assert "[REDACTED]" in messages[0]["content"]
    assert all("internal prompt" not in item["content"] for item in messages)
    assert all("tool output" not in item["content"] for item in messages)


def test_deterministic_summary_uses_only_user_wording() -> None:
    summary, tasks, emotional = deterministic_summary(
        [
            {"role": "assistant", "content": "diagnosis invented by assistant"},
            {"role": "user", "content": "我有些焦虑，请记得明天跟进部署。"},
            {"role": "user", "content": "下一步需要检查 Windows 构建。"},
        ]
    )
    assert "诊断" not in summary
    assert "焦虑" in summary
    assert len(tasks) == 2
    assert emotional["label"] == "anxious"


def test_manual_review_writes_canonical_and_managed_handoff(tmp_path: Path) -> None:
    project, _, engine = _persona(tmp_path)
    original_seed = {
        "id": "existing",
        "summary": "existing reviewed memory",
        "reviewed": True,
    }
    (project / "memory" / "seed.jsonl").write_text(
        json.dumps(original_seed, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    shared = engine.add_manual(
        "xiaoyou",
        summary="用户希望下一次继续检查发布流程。",
        title="发布交接",
        pending_tasks=["检查发布资产"],
        emotional_context={"label": "focused", "note": "保持技术语气"},
    )
    assert shared.status == "pending"
    approved = engine.approve(shared.id, reviewer="tester", sync_scope="shared")
    assert approved.status == "approved"

    canonical = load_jsonl(project / "memory" / "session-summaries.jsonl")
    assert canonical[0]["summary"] == "用户希望下一次继续检查发布流程。"
    assert canonical[0]["pending_tasks"] == ["检查发布资产"]

    seed = load_jsonl(project / "memory" / "seed.jsonl")
    assert any(item["id"] == "existing" for item in seed)
    handoff = next(item for item in seed if item.get("session_summary_id") == shared.id)
    assert handoff["source_type"] == "session-summary"
    assert "Pending tasks" in handoff["summary"]
    assert handoff["reviewed"] is True

    local = engine.add_manual(
        "xiaoyou",
        summary="只保存在本机的摘要。",
        title="本地记录",
    )
    engine.approve(local.id, reviewer="tester", sync_scope="local-only")
    seed = load_jsonl(project / "memory" / "seed.jsonl")
    assert not any(item.get("session_summary_id") == local.id for item in seed)
    canonical = load_jsonl(project / "memory" / "session-summaries.jsonl")
    assert {item["id"] for item in canonical} == {shared.id, local.id}


def test_collect_is_pending_by_default_and_can_be_explicitly_auto_approved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, service, engine = _persona(tmp_path)
    runtime = _runtime(
        service,
        adapter="hermes",
        platform_id="xiaoyou",
        location=str(tmp_path / "profile"),
    )
    service.bind("xiaoyou", runtime.id)

    class Source:
        def collect(self, *, limit: int):
            return [
                SessionSummaryDraft(
                    source_adapter="hermes",
                    source_session_id="session-1",
                    source_title="第一轮",
                    started_at=None,
                    ended_at=None,
                    summary="讨论了部署计划。",
                    sensitivity="internal",
                    generated_by="platform",
                )
            ]

    monkeypatch.setattr(engine, "_source_for_instance", lambda _: Source())
    result = engine.collect("xiaoyou")
    assert result["results"][0]["created"] == 1
    assert engine.session.list_summaries("xiaoyou")[0].status == "pending"

    engine.session.set_policy(
        "xiaoyou",
        {
            "mode": "automatic",
            "auto_approve": {
                "enabled": True,
                "source_adapters": ["hermes"],
                "generated_by": ["platform"],
                "max_sensitivity": "internal",
            },
        },
    )

    class SecondSource:
        def collect(self, *, limit: int):
            return [
                SessionSummaryDraft(
                    source_adapter="hermes",
                    source_session_id="session-2",
                    source_title="第二轮",
                    started_at=None,
                    ended_at=None,
                    summary="完成了无敏感信息的测试。",
                    sensitivity="internal",
                    generated_by="platform",
                )
            ]

    monkeypatch.setattr(engine, "_source_for_instance", lambda _: SecondSource())
    result = engine.collect("xiaoyou")
    assert result["results"][0]["auto_approved"] == 1
    approved = engine.session.list_summaries("xiaoyou", status="approved")
    assert [item.source_session_id for item in approved] == ["session-2"]


def test_plan_suppresses_source_echo_and_destination_repeats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, service, engine = _persona(tmp_path)
    source = _runtime(
        service,
        adapter="hermes",
        platform_id="source",
        location=str(tmp_path / "source"),
    )
    destination = _runtime(
        service,
        adapter="openclaw",
        platform_id="target",
        location=str(tmp_path / "target"),
    )
    service.bind("xiaoyou", source.id)
    service.bind("xiaoyou", destination.id)

    draft = SessionSummaryDraft(
        source_adapter="hermes",
        source_session_id="s1",
        source_title="Source session",
        started_at=None,
        ended_at=None,
        summary="用户要求继续测试下一阶段。",
        pending_tasks=("继续测试",),
        sensitivity="internal",
        generated_by="platform",
    )
    record, _, _ = engine._ingest_draft(
        "xiaoyou", draft, runtime_instance_id=source.id
    )
    engine.approve(record.id, reviewer="tester", sync_scope="shared")

    plan = engine.plan("xiaoyou")
    assert [action["runtime_instance_id"] for action in plan.actions] == [destination.id]
    assert any(
        item["runtime_instance_id"] == source.id
        and item["reason"] == "source-echo-disabled"
        for item in plan.skipped
    )

    monkeypatch.setattr(
        engine,
        "_push_instance",
        lambda persona_id, instance: {"destination": instance.location},
    )
    result = engine.apply(plan)
    assert result["status"] == "success"
    assert engine.plan("xiaoyou").actions == ()


def test_failed_destination_is_retryable_and_not_false_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, service, engine = _persona(tmp_path)
    destination = _runtime(
        service,
        adapter="openclaw",
        platform_id="target",
        location=str(tmp_path / "target"),
    )
    service.bind("xiaoyou", destination.id)
    item = engine.add_manual(
        "xiaoyou", summary="需要重试的任务。", title="重试"
    )
    engine.approve(item.id, reviewer="tester", sync_scope="shared")
    plan = engine.plan("xiaoyou")

    def fail(*_args, **_kwargs):
        raise RuntimeError("destination unavailable")

    monkeypatch.setattr(engine, "_push_instance", fail)
    result = engine.apply(plan)
    assert result["status"] == "failed"
    assert engine.plan("xiaoyou").actions
    propagation = engine.session.list_propagation("xiaoyou")
    assert propagation[0]["status"] == "failed"


def test_raw_preview_requires_policy_and_explicit_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, service, engine = _persona(tmp_path)
    runtime = _runtime(
        service,
        adapter="openclaw",
        platform_id="target",
        location=str(tmp_path / "target"),
    )
    service.bind("xiaoyou", runtime.id)

    class Source:
        def raw_preview(self, session_id: str, *, max_messages: int, max_chars: int):
            return {
                "session_id": session_id,
                "messages": [{"role": "user", "content": "redacted preview"}],
                "persisted": False,
            }

    monkeypatch.setattr(engine, "_source_for_instance", lambda _: Source())
    with pytest.raises(SessionSummaryError, match="explicit experimental"):
        engine.raw_preview(
            "xiaoyou", runtime.id, "s1", confirmed_experimental=False
        )
    with pytest.raises(SessionSummaryError, match="disabled by policy"):
        engine.raw_preview(
            "xiaoyou", runtime.id, "s1", confirmed_experimental=True
        )

    engine.session.set_policy(
        "xiaoyou", {"raw_preview": {"enabled": True}}
    )
    value = engine.raw_preview(
        "xiaoyou", runtime.id, "s1", confirmed_experimental=True
    )
    assert value["persisted"] is False
    assert value["messages"][0]["role"] == "user"


def test_openclaw_platform_summary_source_uses_summary_not_raw_messages() -> None:
    class Runner:
        transport = "local"

        def run(self, arguments, *, timeout=60, check=False):
            if arguments[:2] == ["transcripts", "list"]:
                output = {
                    "transcripts": [
                        {"selector": "daily-1", "title": "Daily", "hasSummary": True}
                    ]
                }
            else:
                output = {
                    "summaryMarkdown": "Reviewed platform summary",
                    "pendingTasks": ["ship release"],
                    "messages": [
                        {"role": "system", "content": "must not import"}
                    ],
                }
            return SimpleNamespace(ok=True, stdout=json.dumps(output), stderr="")

    adapter = SimpleNamespace(runner=Runner())
    drafts = OpenClawSessionSource(adapter, "agent-a").collect(limit=5)
    assert len(drafts) == 1
    assert drafts[0].summary == "Reviewed platform summary"
    assert drafts[0].pending_tasks == ("ship release",)
    assert "must not import" not in drafts[0].summary


def test_cli_web_and_adapter_capabilities_are_exposed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser()
    assert parser.parse_args(["session", "collect", "xiaoyou"]).command == "session"
    assert parser.parse_args(
        ["session", "preview", "xiaoyou", "runtime", "session", "--experimental"]
    ).session_command == "preview"

    assert HermesAdapter().capabilities.session_summary_pull is True
    assert HermesAdapter().capabilities.raw_session_import is True
    assert OpenClawAdapter().capabilities.session_summary_pull is True
    assert OpenClawAdapter().capabilities.raw_session_import is True

    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/sessions" in paths
    assert "/api/sessions/{persona_id}" in paths
    assert "/api/sessions/{persona_id}/collect" in paths
    assert "/api/session-summaries/{summary_id}/approve" in paths
    assert "/api/sessions/{persona_id}/preview" in paths
