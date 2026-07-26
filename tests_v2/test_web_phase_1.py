from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from persona_dock.web import create_app
from persona_dock.web.capabilities import (
    CAPABILITIES,
    capability_summary,
    validate_capabilities,
)
from persona_dock.web.jobs import JobStore


def test_web_capability_registry_is_complete_and_unique() -> None:
    assert validate_capabilities() == []
    assert len({item.id for item in CAPABILITIES}) == len(CAPABILITIES)
    summary = capability_summary()
    assert summary["total"] == len(CAPABILITIES)
    assert summary["ready"] > 0
    assert summary["legacy"] > 0
    assert summary["planned"] >= 0
    assert summary["ready"] + summary["legacy"] + summary["planned"] == summary["total"]
    assert any(item.id == "persona.init" and item.cli_command == "init" for item in CAPABILITIES)
    assert any(item.id == "ai.create" and item.runs_as_job for item in CAPABILITIES)


def test_job_store_persists_status_progress_and_events(tmp_path: Path) -> None:
    path = tmp_path / "control-plane.db"
    store = JobStore(path)
    created = store.create(
        kind="test.operation",
        label="Test operation",
        input={"value": 1},
        persona_id="persona-test",
    )
    assert created.status == "queued"
    assert created.progress == 0
    assert created.input == {"value": 1}
    assert store.list()[0].id == created.id

    running = store.update(created.id, status="running", progress=35)
    assert running.status == "running"
    assert running.progress == 35
    assert running.started_at is not None

    event = store.append_event(created.id, "info", "half way", {"step": 2})
    assert event.job_id == created.id
    assert event.data == {"step": 2}

    completed = store.update(
        created.id,
        status="success",
        output={"result": "ok"},
    )
    assert completed.status == "success"
    assert completed.progress == 100
    assert completed.output == {"result": "ok"}
    assert completed.finished_at is not None

    reopened = JobStore(path)
    assert reopened.get(created.id) == completed
    messages = [item.message for item in reopened.events(created.id)]
    assert messages[0] == "任务已进入队列"
    assert "half way" in messages
    assert messages[-1] == "任务状态：success"


def test_job_store_cancel_is_idempotent(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    job = store.create(kind="test.cancel", label="Cancel me")
    cancelled = store.cancel(job.id)
    assert cancelled.status == "cancelled"
    assert store.cancel(job.id) == cancelled


def test_web_phase_one_routes_are_registered() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/v1/meta" in paths
    assert "/api/v1/capabilities" in paths
    assert "/api/v1/dashboard" in paths
    assert "/api/v1/jobs" in paths
    assert "/api/v1/jobs/{job_id}/events" in paths
    assert "/assets/app.css" in paths
    assert "/assets/app.js" in paths
    assert "/canonical" in paths
    assert "/hermes" in paths
    assert "/openclaw" in paths
    assert "/sync" in paths
    assert "/sessions" in paths


def test_embedded_web_shell_uses_restrained_local_assets() -> None:
    root = files("persona_dock.web.static")
    html = root.joinpath("index.html").read_text(encoding="utf-8")
    css = root.joinpath("app.css").read_text(encoding="utf-8")
    javascript = root.joinpath("app.js").read_text(encoding="utf-8")

    assert 'href="/assets/app.css"' in html
    assert 'src="/assets/app.js"' in html
    assert "PersonaDock" in html
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert ".data-table" in css
    assert ".sidebar" in css
    assert "/api/v1/meta" in javascript
    assert "/api/v1/capabilities" in javascript
    assert "sessionStorage" in javascript
