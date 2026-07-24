from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from persona_dock.io import load_jsonl, write_jsonl
from persona_dock.project import init_project
from persona_dock.registry import RegistryService
from persona_dock.registry.database import RegistryDatabase
from persona_dock.sync_cli import build_parser
from persona_dock.sync_engine import SyncEngine, SyncError
from persona_dock.sync_models import (
    classify_sensitivity,
    memory_fingerprint,
    memory_key,
)
from persona_dock.sync_registry import SyncRegistry
from persona_dock.web import create_app


def _service(tmp_path: Path) -> tuple[Path, RegistryService, SyncEngine]:
    project = init_project(
        tmp_path / "persona",
        "xiaoyou",
        "小柚",
        schema_version=3,
    )
    service = RegistryService(RegistryDatabase(tmp_path / "personadock.db"))
    service.register_persona(
        persona_id="xiaoyou",
        name="小柚",
        version="0.1.0",
        source_path=project,
        schema_version=3,
        summary="测试人格同步",
    )
    return project, service, SyncEngine(service)


def _runtime(
    service: RegistryService,
    *,
    adapter: str,
    platform_id: str,
    location: str,
    pull: bool = True,
    push: bool = True,
):
    instance = service.upsert_runtime_instance(
        adapter=adapter,
        transport="local",
        platform_instance_id=platform_id,
        display_name=platform_id,
        location=location,
        capabilities={"memory_pull": pull, "memory_push": push},
        metadata={"discovery_source": "test"},
    )
    service.bind("xiaoyou", instance.id)
    return instance


def test_registry_v1_database_migrates_to_cumulative_schema_v3(tmp_path: Path) -> None:
    path = tmp_path / "personadock.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE registry_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO registry_meta(key, value) VALUES('schema_version', '1')")
    connection.commit()
    connection.close()

    database = RegistryDatabase(path)
    database.initialize()
    assert database.schema_version() == 3
    with database.session() as migrated:
        tables = {
            row[0]
            for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        "sync_policies",
        "memory_items",
        "sync_conflicts",
        "sync_runs",
        "propagation_log",
        "session_summary_policies",
        "session_summaries",
        "session_summary_propagation",
    } <= tables


def test_default_policy_is_review_first_and_auto_approval_is_off(tmp_path: Path) -> None:
    _, _, engine = _service(tmp_path)
    policy = engine.sync.get_policy("xiaoyou")
    assert policy.config["mode"] == "review"
    assert policy.config["auto_approve"]["enabled"] is False
    assert policy.config["push"]["reviewed_only"] is True
    assert policy.config["push"]["echo_to_source"] is False
    assert policy.config["definition_sync"]["pull"] == "snapshot-review"


def test_candidate_ingest_deduplicates_and_escalates_sensitive_content(tmp_path: Path) -> None:
    project, _, engine = _service(tmp_path)
    write_jsonl(
        project / ".private" / "memory-candidates.jsonl",
        [
            {
                "id": "h1",
                "type": "preference",
                "summary": "用户喜欢咖啡",
                "sensitivity": "internal",
                "source": {"adapter": "hermes", "profile": "xiaoyou"},
            },
            {
                "id": "o1",
                "type": "preference",
                "summary": "用户喜欢咖啡",
                "sensitivity": "internal",
                "source": {"adapter": "openclaw", "agent": "xiaoyou"},
            },
            {
                "id": "secret",
                "type": "note",
                "summary": "API key sk-1234567890abcdef must not sync",
                "sensitivity": "internal",
                "source": {"adapter": "openclaw", "agent": "xiaoyou"},
            },
        ],
    )

    result = engine.ingest_candidate_file("xiaoyou")
    assert result["inserted"] == 2
    assert result["duplicates"] == 1
    items = engine.sync.list_memory_items("xiaoyou")
    assert len(items) == 2
    assert all(item.status == "pending" for item in items)
    secret = next(item for item in items if "API key" in item.summary)
    assert secret.sensitivity == "restricted"


def test_automatic_policy_only_approves_whitelisted_low_sensitivity_items(tmp_path: Path) -> None:
    project, _, engine = _service(tmp_path)
    engine.sync.set_policy(
        "xiaoyou",
        {
            "mode": "automatic",
            "auto_approve": {
                "enabled": True,
                "source_adapters": ["hermes"],
                "memory_types": ["preference"],
                "max_sensitivity": "internal",
            },
        },
    )
    write_jsonl(
        project / ".private" / "memory-candidates.jsonl",
        [
            {
                "id": "safe",
                "type": "preference",
                "summary": "用户偏好简短回复",
                "sensitivity": "internal",
                "source": {"adapter": "hermes", "profile": "xiaoyou"},
            },
            {
                "id": "private",
                "type": "preference",
                "summary": "用户手机号是 +1 415 555 0111",
                "sensitivity": "internal",
                "source": {"adapter": "hermes", "profile": "xiaoyou"},
            },
            {
                "id": "other-source",
                "type": "preference",
                "summary": "用户喜欢夜间工作",
                "sensitivity": "internal",
                "source": {"adapter": "openclaw", "agent": "xiaoyou"},
            },
        ],
    )

    result = engine.ingest_candidate_file("xiaoyou")
    assert result["auto_approved"] == 1
    approved = engine.sync.list_memory_items("xiaoyou", status="approved")
    pending = engine.sync.list_memory_items("xiaoyou", status="pending")
    assert [item.summary for item in approved] == ["用户偏好简短回复"]
    assert len(pending) == 2
    seed = load_jsonl(project / "memory" / "seed.jsonl")
    assert any(record["summary"] == "用户偏好简短回复" for record in seed)
    assert all(record.get("reviewed") is True for record in seed)


def test_conflicting_candidate_requires_explicit_resolution(tmp_path: Path) -> None:
    project, _, engine = _service(tmp_path)
    write_jsonl(
        project / "memory" / "seed.jsonl",
        [
            {
                "id": "existing",
                "type": "preference",
                "memory_key": "favorite-drink",
                "summary": "用户喜欢咖啡",
                "reviewed": True,
                "sync_scope": "shared",
            }
        ],
    )
    engine.import_reviewed_memory("xiaoyou")
    write_jsonl(
        project / ".private" / "memory-candidates.jsonl",
        [
            {
                "id": "candidate",
                "type": "preference",
                "memory_key": "favorite-drink",
                "summary": "用户现在不喜欢咖啡",
                "source": {"adapter": "openclaw", "agent": "xiaoyou"},
            }
        ],
    )

    result = engine.ingest_candidate_file("xiaoyou")
    assert result["conflicts"] == 1
    conflict = engine.sync.list_conflicts("xiaoyou", status="pending")[0]
    candidate = engine.sync.get_memory_item(conflict.candidate_id)
    assert candidate is not None
    with pytest.raises(SyncError, match="unresolved conflict"):
        engine.approve(candidate.id)

    resolved = engine.resolve_conflict(
        conflict.id,
        "replace",
        reviewer="tester",
    )
    assert resolved["status"] == "resolved"
    approved = engine.sync.list_memory_items("xiaoyou", status="approved")
    superseded = engine.sync.list_memory_items("xiaoyou", status="superseded")
    assert any(item.summary == "用户现在不喜欢咖啡" for item in approved)
    assert any(item.summary == "用户喜欢咖啡" for item in superseded)
    seed = load_jsonl(project / "memory" / "seed.jsonl")
    assert [record["summary"] for record in seed] == ["用户现在不喜欢咖啡"]


def test_plan_skips_source_echo_and_previously_propagated_items(tmp_path: Path) -> None:
    _, service, engine = _service(tmp_path)
    hermes = _runtime(
        service,
        adapter="hermes",
        platform_id="xiaoyou",
        location=str(tmp_path / "hermes"),
    )
    openclaw = _runtime(
        service,
        adapter="openclaw",
        platform_id="xiaoyou",
        location=str(tmp_path / "openclaw"),
    )
    summary = "用户喜欢咖啡"
    item, _ = engine.sync.upsert_memory_item(
        persona_id="xiaoyou",
        fingerprint=memory_fingerprint(summary, "preference"),
        memory_key=memory_key(summary, "preference"),
        memory_type="preference",
        summary=summary,
        sensitivity="internal",
        sync_scope="shared",
        status="pending",
        source_adapter="hermes",
        source_runtime_instance_id=hermes.id,
        source_record_id="source-1",
        source_path="memories/MEMORY.md",
        metadata={"source": {"adapter": "hermes", "profile": "xiaoyou"}},
    )
    approved = engine.approve(item.id, reviewer="tester")

    first = engine.plan("xiaoyou")
    assert len(first.memory_actions) == 1
    assert first.memory_actions[0]["runtime_instance_id"] == openclaw.id
    assert any(
        skipped.get("runtime_instance_id") == hermes.id
        and skipped.get("reason") == "source echo disabled"
        for skipped in first.skipped
    )

    engine.sync.record_propagation(
        persona_id="xiaoyou",
        memory_item_id=approved.id,
        source_runtime_instance_id=hermes.id,
        destination_runtime_instance_id=openclaw.id,
        content_hash=approved.fingerprint,
        operation="memory-push",
        status="success",
        details={"test": True},
    )
    second = engine.plan("xiaoyou")
    assert second.memory_actions == ()
    assert any(
        skipped.get("runtime_instance_id") == openclaw.id
        and skipped.get("reason") == "already propagated"
        for skipped in second.skipped
    )


def test_apply_groups_destination_push_and_records_propagation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, service, engine = _service(tmp_path)
    openclaw = _runtime(
        service,
        adapter="openclaw",
        platform_id="xiaoyou",
        location=str(tmp_path / "workspace"),
    )
    item, _ = engine.sync.upsert_memory_item(
        persona_id="xiaoyou",
        fingerprint=memory_fingerprint("共享事实", "fact"),
        memory_key="shared-fact",
        memory_type="fact",
        summary="共享事实",
        sensitivity="internal",
        sync_scope="shared",
        status="pending",
        source_adapter=None,
        source_runtime_instance_id=None,
        source_record_id=None,
        source_path=None,
        metadata={"source": "test"},
    )
    engine.approve(item.id, reviewer="tester")
    calls: list[str] = []
    monkeypatch.setattr(
        engine,
        "_push_memory_destination",
        lambda persona_id, instance: calls.append(instance.id) or {"ok": True},
    )

    plan = engine.plan("xiaoyou")
    result = engine.apply(plan)
    assert result["status"] == "success"
    assert calls == [openclaw.id]
    log = engine.sync.propagation_log("xiaoyou")
    assert len(log) == 1
    assert log[0]["destination_runtime_instance_id"] == openclaw.id
    binding = service.list_bindings("xiaoyou")[0]
    refreshed = service.list_bindings("xiaoyou")[0]
    assert binding.id == refreshed.id
    assert refreshed.last_synced_at is not None


def test_collect_uses_bound_runtime_and_ingests_platform_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, service, engine = _service(tmp_path)
    hermes = _runtime(
        service,
        adapter="hermes",
        platform_id="xiaoyou",
        location=str(tmp_path / "hermes"),
    )

    def fake_pull(persona_id: str, **kwargs):
        write_jsonl(
            project / ".private" / "memory-candidates.jsonl",
            [
                {
                    "id": "runtime-candidate",
                    "type": "fact",
                    "summary": "从 Hermes 拉取的事实",
                    "source": {
                        "adapter": "hermes",
                        "runtime_instance_id": hermes.id,
                        "profile": "xiaoyou",
                        "path": "memories/MEMORY.md",
                    },
                    "reviewed": False,
                    "sensitivity": "private",
                    "sync_scope": "local-only",
                }
            ],
        )
        return {"added": 1}

    monkeypatch.setattr("persona_dock.sync_engine.pull_hermes_memory_candidates", fake_pull)
    result = engine.collect("xiaoyou")
    assert result["platform_results"][0]["status"] == "success"
    assert result["ingest"]["inserted"] == 1
    pending = engine.sync.list_memory_items("xiaoyou", status="pending")
    assert len(pending) == 1
    assert pending[0].source_runtime_instance_id == hermes.id
    assert pending[0].sync_scope == "local-only"


def test_definition_drift_is_previewed_but_never_auto_pulled(tmp_path: Path) -> None:
    _, service, engine = _service(tmp_path)
    instance = _runtime(
        service,
        adapter="hermes",
        platform_id="xiaoyou",
        location=str(tmp_path / "hermes"),
        pull=False,
        push=False,
    )
    plan = engine.plan("xiaoyou")
    assert len(plan.definition_actions) == 1
    action = plan.definition_actions[0]
    assert action["runtime_instance_id"] == instance.id
    assert action["requires_confirmation"] is True
    assert action["definition_pull"] == "snapshot-review"


def test_sensitivity_classifier_never_downgrades_declared_private() -> None:
    assert classify_sensitivity("ordinary note", "private") == "private"
    assert classify_sensitivity("password: hunter2", "internal") == "restricted"
    assert classify_sensitivity("email me at user@example.com", "internal") == "private"


def test_sync_cli_and_web_routes_are_exposed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    parser = build_parser()
    parsed = parser.parse_args(["sync", "plan", "xiaoyou", "--json"])
    assert parsed.sync_command == "plan"
    review = parser.parse_args(
        ["sync", "review", "resolve", "conflict-id", "--resolution", "keep-both"]
    )
    assert review.sync_review_command == "resolve"

    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/sync" in paths
    assert "/api/sync/{persona_id}" in paths
    assert "/api/sync/{persona_id}/policy" in paths
    assert "/api/sync/{persona_id}/collect" in paths
    assert "/api/sync/{persona_id}/memory" in paths
    assert "/api/sync/memory/{item_id}/approve" in paths
    assert "/api/sync/memory/{item_id}/reject" in paths
    assert "/api/sync/conflicts/{conflict_id}/resolve" in paths
    assert "/api/sync/{persona_id}/plan" in paths
    assert "/api/sync/{persona_id}/apply" in paths
