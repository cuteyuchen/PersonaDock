from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from persona_dock.cli import build_parser
from persona_dock.deployment.plans import build_deployment_plan
from persona_dock import doctor as doctor_module
from persona_dock.adapters.base import AdapterCapabilities, AdapterDoctorResult
from persona_dock.doctor import doctor_report, render_doctor
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


def _doctor_result(
    adapter: str,
    *,
    status: str,
    container: str | None = None,
) -> AdapterDoctorResult:
    return AdapterDoctorResult(
        adapter=adapter,
        available=status == "ready",
        executable=(f"docker exec {container} {adapter}" if container else adapter),
        version="1.0.0" if status != "unavailable" else None,
        status=status,
        message=f"{adapter} {status}",
        capabilities=AdapterCapabilities(docker=True),
        details={
            "native": True,
            "transport": "docker" if container else "local",
            "container": container,
        },
    )


def test_doctor_auto_discovers_unique_docker_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeHermes:
        def __init__(self, *, container: str | None = None, **_: object) -> None:
            self.container = container

        def doctor(self) -> AdapterDoctorResult:
            return _doctor_result(
                "hermes",
                status="ready" if self.container else "unavailable",
                container=self.container,
            )

    class FakeOpenClaw:
        def __init__(self, *, container: str | None = None, **_: object) -> None:
            self.container = container

        def doctor(self) -> AdapterDoctorResult:
            return _doctor_result(
                "openclaw",
                status="ready" if self.container else "unavailable",
                container=self.container,
            )

    calls: list[tuple[str, tuple[str, ...]]] = []

    def probe(
        containers: list[dict[str, str]],
        *,
        cli: str,
        arguments: list[str],
        **_: object,
    ) -> list[dict[str, str]]:
        calls.append((cli, tuple(arguments)))
        name = "hermes-box" if cli == "hermes" else "openclaw-box"
        return [item for item in containers if item["name"] == name]

    monkeypatch.setattr(doctor_module, "HermesAdapter", FakeHermes)
    monkeypatch.setattr(doctor_module, "OpenClawAdapter", FakeOpenClaw)
    monkeypatch.setattr(
        doctor_module,
        "_list_running_docker_containers",
        lambda **_: (
            [
                {"name": "openclaw-box", "image": "openclaw:test"},
                {"name": "hermes-box", "image": "hermes:test"},
                {"name": "other", "image": "busybox"},
            ],
            {"status": "ok", "reason": "scanned", "message": "ok", "container_count": 3},
        ),
    )
    monkeypatch.setattr(doctor_module, "_docker_executable", lambda: "docker")
    monkeypatch.setattr(doctor_module, "_probe_containers_for_cli", probe)

    report = doctor_report()
    adapters = {item["adapter"]: item for item in report["adapters"]}
    assert adapters["hermes"]["status"] == "ready"
    assert adapters["hermes"]["details"]["container"] == "hermes-box"
    assert adapters["hermes"]["details"]["discovery_source"] == "docker-auto"
    assert adapters["openclaw"]["status"] == "ready"
    assert adapters["openclaw"]["details"]["container"] == "openclaw-box"
    assert calls == [("hermes", ("version",)), ("openclaw", ("--version",))]


def test_doctor_reports_ambiguous_docker_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = _doctor_result("hermes", status="unavailable")
    ready = lambda container: _doctor_result("hermes", status="ready", container=container)
    monkeypatch.setattr(
        doctor_module,
        "_probe_containers_for_cli",
        lambda *_args, **_kwargs: [
            {"name": "hermes-a", "image": "image-a", "version": "1.0.0"},
            {"name": "hermes-b", "image": "image-b", "version": "1.0.0"},
        ],
    )

    result = doctor_module._resolve_docker_adapter(
        adapter_name="hermes",
        local_result=local,
        containers=[{"name": "ignored", "image": "ignored"}],
        docker_scan={"status": "ok", "reason": "scanned", "message": "ok", "container_count": 2},
        docker_executable="docker",
        cli="hermes",
        arguments=["version"],
        factory=lambda name: SimpleNamespace(doctor=lambda: ready(name)),
    )
    assert result.status == "ambiguous"
    assert result.available is False
    assert [item["container"] for item in result.details["candidates"]] == ["hermes-a", "hermes-b"]
    assert "--container <name>" in render_doctor(
        {"personadock_version": "1.0.0", "platform": "test", "machine": "test", "python_version": "test", "adapters": [result.to_dict()]}
    )


@pytest.mark.parametrize("status", ["ready", "degraded"])
def test_doctor_does_not_fallback_when_local_adapter_is_not_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    local = _doctor_result("openclaw", status=status)
    monkeypatch.setattr(
        doctor_module,
        "_probe_containers_for_cli",
        lambda *_args, **_kwargs: pytest.fail("Docker probe must not run for a degraded local adapter"),
    )

    result = doctor_module._resolve_docker_adapter(
        adapter_name="openclaw",
        local_result=local,
        containers=[{"name": "openclaw", "image": "openclaw:test"}],
        docker_scan={"status": "ok"},
        docker_executable="docker",
        cli="openclaw",
        arguments=["--version"],
        factory=lambda _: pytest.fail("Docker adapter must not be instantiated"),
    )
    assert result.status == status
    assert result.details["discovery_source"] == "local"


def test_docker_container_listing_handles_daemon_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        doctor_module,
        "_run_command",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="permission denied"),
    )
    containers, scan = doctor_module._list_running_docker_containers(
        docker_executable="docker"
    )
    assert containers == []
    assert scan["reason"] == "docker-daemon-unavailable"
    assert scan["message"] == "permission denied"


def test_docker_container_listing_handles_missing_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(doctor_module, "_docker_executable", lambda: None)
    containers, scan = doctor_module._list_running_docker_containers()
    assert containers == []
    assert scan["reason"] == "docker-cli-missing"


def test_docker_probe_timeout_is_not_a_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def docker_timeout(*_args: object, **_kwargs: object) -> None:
        raise doctor_module.subprocess.TimeoutExpired(["docker"], 5)

    monkeypatch.setattr(doctor_module, "_run_command", docker_timeout)
    result = doctor_module._probe_container_cli(
        docker_executable="docker",
        container="stopped-during-check",
        cli="hermes",
        arguments=["version"],
    )
    assert result["present"] is False
    assert "timed out" in result["error"]


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
