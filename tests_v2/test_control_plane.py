from __future__ import annotations

from pathlib import Path

import pytest

from persona_dock.cli import build_parser
from persona_dock.deployment.plans import build_deployment_plan
from persona_dock.doctor import doctor_report
from persona_dock.packaging import pack_project
from persona_dock.project import init_project
from persona_dock.targeting import TargetResolutionError, detect_hermes_target
from persona_dock.web import create_app


def _package(tmp_path: Path) -> Path:
    project = init_project(tmp_path / "persona", "persona", "测试人格")
    return pack_project(project)


def test_windows_hermes_detects_local_app_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import persona_dock.targeting as targeting

    home = tmp_path / "home"
    local_app_data = tmp_path / "AppData" / "Local"
    hermes = local_app_data / "hermes"
    hermes.mkdir(parents=True)
    (hermes / "config.yaml").write_text("model: test\n", encoding="utf-8")
    (hermes / "SOUL.md").write_text("# Existing soul\n", encoding="utf-8")

    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(targeting.platform, "system", lambda: "Windows")
    monkeypatch.setattr(targeting.Path, "home", classmethod(lambda cls: home))

    detected = detect_hermes_target()
    assert detected.path == hermes.resolve()
    assert detected.source == "windows-local-app-data"
    assert detected.confidence >= 40


def test_explicit_target_environment_is_trusted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "custom-hermes"
    monkeypatch.setenv("HERMES_HOME", str(target))
    detected = detect_hermes_target()
    assert detected.path == target.resolve()
    assert detected.source == "HERMES_HOME"


def test_deployment_plan_is_read_only_and_file_level(tmp_path: Path) -> None:
    package = _package(tmp_path)
    destination = tmp_path / "agent"
    destination.mkdir()
    existing = destination / "SOUL.md"
    existing.write_text("old\n", encoding="utf-8")

    plan = build_deployment_plan(package, "hermes", destination)

    assert plan.destination == str(destination.resolve())
    assert plan.destination_source == "explicit-path"
    assert any(item.destination == str(existing) and item.exists for item in plan.operations)
    assert existing.read_text(encoding="utf-8") == "old\n"
    assert plan.requires_confirmation is True


def test_ambiguous_or_missing_target_stops_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import persona_dock.targeting as targeting

    package = _package(tmp_path)

    def fail(_: str):
        raise TargetResolutionError("no trusted target")

    monkeypatch.setattr(targeting, "detect_local_target", fail)
    with pytest.raises(TargetResolutionError, match="no trusted target"):
        build_deployment_plan(package, "hermes")


def test_legacy_docker_plan_requires_explicit_absolute_path(tmp_path: Path) -> None:
    package = _package(tmp_path)
    with pytest.raises(ValueError, match="requires an explicit"):
        build_deployment_plan(package, "hermes", container="hermes-app")
    with pytest.raises(ValueError, match="absolute"):
        build_deployment_plan(package, "hermes", "relative/path", "hermes-app")


def test_doctor_and_web_use_shared_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path / "openclaw"))

    report = doctor_report()
    assert {item["adapter"] for item in report["adapters"]} == {
        "hermes",
        "openclaw",
        "generic",
    }
    assert all("capabilities" in item for item in report["adapters"])

    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/health" in paths
    assert "/api/doctor" in paths
    assert "/api/plans/deploy" in paths
    assert "/" in paths


def test_cli_exposes_phase_zero_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["doctor"]).command == "doctor"
    assert parser.parse_args(["serve", "--no-browser"]).command == "serve"
    deploy = parser.parse_args(
        [
            "deploy",
            "persona.personapack",
            "--target",
            "hermes",
            "--path",
            "/tmp/hermes",
            "--dry-run",
        ]
    )
    assert deploy.command == "deploy"
    assert deploy.dry_run is True
