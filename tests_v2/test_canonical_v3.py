from __future__ import annotations

import json
from pathlib import Path

import pytest

from persona_dock.canonical_cli import build_parser, main
from persona_dock.compiler import compile_project
from persona_dock.core.diff import diff_personas
from persona_dock.core.migration import migrate_project_to_v3
from persona_dock.core.models import load_canonical_persona
from persona_dock.core.testing import run_persona_tests
from persona_dock.io import dump_yaml, load_yaml
from persona_dock.packaging import inspect_package, pack_project
from persona_dock.project import PROJECT_FILE, init_project, validate_project
from persona_dock.web import create_app


def test_cli_init_creates_v3_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    project = tmp_path / "persona"
    assert main(["init", str(project), "--id", "persona", "--name", "测试人格"]) == 0
    value = load_yaml(project / PROJECT_FILE)
    assert value["schema_version"] == 3
    assert len(value["behaviors"]) == 3
    assert validate_project(project) == []


def test_v2_migration_preserves_source_and_creates_v3(
    tmp_path: Path,
) -> None:
    source = init_project(tmp_path / "legacy", "legacy", "旧人格", schema_version=2)
    source_before = (source / PROJECT_FILE).read_bytes()

    result = migrate_project_to_v3(source, output=tmp_path / "canonical")
    canonical = Path(result.project)
    value = load_canonical_persona(canonical)

    assert result.from_schema == 2
    assert result.to_schema == 3
    assert result.changed is True
    assert (source / PROJECT_FILE).read_bytes() == source_before
    assert value["schema_version"] == 3
    assert value["identity"]["statement"]
    assert len(value["behaviors"]) == 3
    assert all(item["source_type"] == "reviewed-existing" for item in value["behaviors"])
    assert validate_project(canonical) == []


def test_in_place_migration_creates_backup(tmp_path: Path) -> None:
    source = init_project(tmp_path / "legacy", "legacy", "旧人格", schema_version=2)
    result = migrate_project_to_v3(source, in_place=True, backup=True)
    assert result.backup is not None
    backup = Path(result.backup)
    assert (backup / PROJECT_FILE).is_file()
    assert load_yaml(backup / PROJECT_FILE)["schema_version"] == 2
    assert load_yaml(source / PROJECT_FILE)["schema_version"] == 3


def test_v3_compiler_and_personapack_manifest_v2(tmp_path: Path) -> None:
    project = init_project(tmp_path / "persona", "persona", "测试人格", schema_version=3)
    build = compile_project(project)
    soul = (build / "targets/hermes/SOUL.md").read_text(encoding="utf-8")
    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))

    assert "人格行为路由" in soul
    assert "memory-retrieval" in soul
    assert manifest["format_version"] == 2
    assert manifest["schema_version"] == 3
    assert manifest["canonical"]["behavior_rules"] == 3
    assert manifest["privacy"]["unreviewed_memory_included"] is False

    package = pack_project(project)
    info = inspect_package(package)
    assert info["integrity"] == "ok"
    assert info["schema_version"] == 3


def test_semantic_diff_tracks_rules_and_fields(tmp_path: Path) -> None:
    before = init_project(tmp_path / "before", "persona", "测试人格", schema_version=3)
    after = init_project(tmp_path / "after", "persona", "测试人格", schema_version=3)
    value = load_yaml(after / PROJECT_FILE)
    value["version"] = "0.2.0"
    value["voice"]["style"] = "使用更简短、自然的中文表达。"
    value["behaviors"].append(
        {
            "id": "technical-answer",
            "trigger": {"intent": "technical", "conditions": ["用户询问技术问题"]},
            "behavior": ["先给结论", "再给可执行步骤"],
            "constraints": ["不编造命令输出"],
            "priority": "medium",
            "confidence": "explicit",
            "source_type": "explicit-design",
            "evidence": [],
            "tests": ["technical-answer"],
        }
    )
    (after / PROJECT_FILE).write_text(dump_yaml(value), encoding="utf-8")

    report = diff_personas(before, after)
    assert report.changed is True
    assert report.added_behaviors == ("technical-answer",)
    assert {item.path for item in report.field_changes} == {"version", "voice.style"}


def test_persona_tests_enforce_high_priority_coverage(tmp_path: Path) -> None:
    project = init_project(tmp_path / "persona", "persona", "测试人格", schema_version=3)
    report = run_persona_tests(project)
    assert report.ok is True
    assert report.failed == 0

    value = load_yaml(project / PROJECT_FILE)
    value["behaviors"].append(
        {
            "id": "untested-critical",
            "trigger": {"intent": "critical", "conditions": ["测试"]},
            "behavior": ["执行规则"],
            "constraints": [],
            "priority": "critical",
            "confidence": "explicit",
            "source_type": "explicit-design",
            "evidence": [],
            "tests": [],
        }
    )
    (project / PROJECT_FILE).write_text(dump_yaml(value), encoding="utf-8")
    report = run_persona_tests(project)
    assert report.ok is False
    coverage = next(item for item in report.results if item.id == "coverage-high-priority-behaviors")
    assert "untested-critical" in coverage.message


def test_observed_behavior_requires_evidence(tmp_path: Path) -> None:
    project = init_project(tmp_path / "persona", "persona", "测试人格", schema_version=3)
    value = load_yaml(project / PROJECT_FILE)
    value["behaviors"][0]["source_type"] = "observed-evidence"
    value["behaviors"][0]["evidence"] = []
    (project / PROJECT_FILE).write_text(dump_yaml(value), encoding="utf-8")
    errors = validate_project(project)
    assert any("requires evidence refs" in error for error in errors)


def test_canonical_cli_and_web_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONADOCK_HOME", str(tmp_path / "state"))
    parser = build_parser()
    assert parser.parse_args(["migrate", ".", "--in-place"]).command == "migrate"
    assert parser.parse_args(["diff", "a", "b"]).command == "diff"
    assert parser.parse_args(["test", "."]).command == "test"

    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/canonical" in paths
    assert "/api/personas/{persona_id}/canonical" in paths
    assert "/api/personas/{persona_id}/migrate-v3" in paths
    assert "/api/personas/{persona_id}/tests" in paths
    assert "/api/personas/diff" in paths
