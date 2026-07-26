from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest

from persona_dock.web import create_app
from persona_dock.web.governance_api import _run_job
from persona_dock.web.jobs import JobStore
from persona_dock.web.version import WEB_REFACTOR_PHASE


def test_governance_job_store_records_only_operation_metadata(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "control-plane.db")
    result = _run_job(
        store,
        kind="session.collect",
        label="Collect summaries",
        persona_id="demo",
        input={"persona_id": "demo"},
        operation=lambda: {"collected": 2},
    )
    assert result["job"]["status"] == "success"
    assert result["job"]["input"] == {"persona_id": "demo"}
    assert result["result"] == {"collected": 2}
    stored = store.get(result["job"]["id"])
    assert stored is not None
    assert "summary" not in stored.input
    assert "session_id" not in stored.input


def test_governance_job_failure_is_persisted(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")

    def fail() -> dict[str, object]:
        raise ValueError("adapter unavailable")

    with pytest.raises(ValueError, match="adapter unavailable"):
        _run_job(
            store,
            kind="memory.collect",
            label="Collect memory",
            persona_id="demo",
            input={"persona_id": "demo"},
            operation=fail,
        )
    assert store.list()[0].status == "failed"
    assert store.list()[0].error == "adapter unavailable"


def test_phase_six_routes_assets_and_explicit_confirmation_contracts() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    for path in (
        "/api/v1/governance/memory/{persona_id}/collect",
        "/api/v1/governance/memory/{persona_id}/apply",
        "/api/v1/governance/sessions/{persona_id}/collect",
        "/api/v1/governance/sessions/{persona_id}/apply",
        "/api/sync/{persona_id}/conflicts",
        "/api/sessions/{persona_id}/preview",
    ):
        assert path in paths
    assert WEB_REFACTOR_PHASE >= 6

    root = files("persona_dock")
    html = root.joinpath("web/static/index.html").read_text(encoding="utf-8")
    css = root.joinpath("web/static/governance.css").read_text(encoding="utf-8")
    javascript = root.joinpath("web/static/governance.js").read_text(encoding="utf-8")
    api_source = root.joinpath("web/governance_api.py").read_text(encoding="utf-8")

    assert 'href="/assets/governance.css"' in html
    assert 'src="/assets/governance.js"' in html
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert "原始 Session 同步" in javascript
    assert "experimental: true" in javascript
    assert "输入 APPLY" in javascript
    assert api_source.count("if not request.confirmed") == 2
    assert 'input={"persona_id": persona_id}' in api_source
    assert '"session_id"' not in api_source
