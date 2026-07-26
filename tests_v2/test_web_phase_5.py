from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from persona_dock.application import (
    ArtifactApplicationService,
    ArtifactStore,
    DeploymentApplicationService,
    DeploymentPlanChangedError,
    DeploymentStore,
)
from persona_dock.registry import RegistryService
from persona_dock.registry.database import RegistryDatabase
from persona_dock.web import create_app
from persona_dock.web.version import WEB_REFACTOR_PHASE


@dataclass(frozen=True, slots=True)
class FakePlan:
    id: str
    target: str
    persona_id: str
    persona_version: str
    profile: str
    transport: str
    runtime_state: str
    snapshot_path: str | None = None
    commands: tuple[tuple[str, ...], ...] = (("profile", "show"),)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["commands"] = [list(item) for item in self.commands]
        value["artifact"] = {
            "path": f"/tmp/{self.id}",
            "package_sha256": "a" * 64,
        }
        value["preserves"] = ["credentials", "sessions"]
        value["warnings"] = []
        return value


@dataclass(frozen=True, slots=True)
class FakeResult:
    deployment_id: str
    profile: str
    snapshot_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _service(tmp_path: Path, *, changed: bool = False):
    registry = RegistryService(RegistryDatabase(tmp_path / "registry.db"))
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    package = artifact_store.output("exports", "demo.personapack")
    package.write_bytes(b"fake-personapack")
    calls = {"plan": 0, "apply": [], "rollback": []}

    def planner(*_args, **_kwargs):
        calls["plan"] += 1
        runtime_state = "changed" if changed and calls["plan"] > 1 else "stable"
        return FakePlan(
            id=f"generated-{calls['plan']}",
            target="hermes",
            persona_id="demo",
            persona_version="1.0.0",
            profile="demo",
            transport="local",
            runtime_state=runtime_state,
        )

    def applier(plan, **_kwargs):
        calls["apply"].append(plan.id)
        return FakeResult(
            deployment_id=plan.id,
            profile=plan.profile,
            snapshot_path=None,
        )

    def rollback(**kwargs):
        calls["rollback"].append(kwargs)
        return {"action": "deleted", "profile": kwargs["profile"]}

    service = DeploymentApplicationService(
        registry,
        ArtifactApplicationService(registry, artifact_store),
        DeploymentStore(tmp_path / "control-plane.db"),
        hermes_planner=planner,
        hermes_applier=applier,
        hermes_rollback=rollback,
        hermes_adapter_factory=lambda **_: object(),
    )
    request = {
        "target": "hermes",
        "persona_id": None,
        "package_path": str(package),
        "profile": "demo",
        "activate": False,
        "alias": False,
        "container": None,
    }
    return service, request, calls


def test_deployment_token_is_hash_only_and_identity_survives_apply(tmp_path: Path) -> None:
    service, request, calls = _service(tmp_path)
    created = service.create_plan(request)
    token = created["confirmation_token"]
    record = created["deployment"]

    assert token not in str(record)
    assert record["status"] == "planned"
    with sqlite3.connect(tmp_path / "control-plane.db") as connection:
        row = connection.execute(
            "SELECT token_hash, request_json, plan_json FROM web_deployment_plans WHERE id = ?",
            (record["id"],),
        ).fetchone()
    assert row is not None
    assert row[0] != token
    assert token not in row[1]
    assert token not in row[2]

    applied = service.apply(record["id"], confirmation_token=token)
    assert applied["status"] == "applied"
    assert applied["output"]["deployment_id"] == record["id"]
    assert calls["apply"] == [record["id"]]

    rolled_back = service.rollback(record["id"])
    assert rolled_back["status"] == "rolled-back"
    assert rolled_back["output"]["rollback"]["action"] == "deleted"
    assert len(calls["rollback"]) == 1


def test_deployment_rejects_invalid_token(tmp_path: Path) -> None:
    service, request, _ = _service(tmp_path)
    created = service.create_plan(request)
    with pytest.raises(PermissionError, match="confirmation token"):
        service.apply(created["deployment"]["id"], confirmation_token="not-the-token")


def test_deployment_rejects_changed_runtime_state(tmp_path: Path) -> None:
    service, request, calls = _service(tmp_path, changed=True)
    created = service.create_plan(request)
    with pytest.raises(DeploymentPlanChangedError, match="state changed"):
        service.apply(
            created["deployment"]["id"],
            confirmation_token=created["confirmation_token"],
        )
    assert calls["apply"] == []


def test_phase_five_routes_assets_and_security_contracts() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    for path in (
        "/api/v1/deployment-plans",
        "/api/v1/deployments",
        "/api/v1/deployments/{deployment_id}",
        "/api/v1/deployments/{deployment_id}/rollback",
    ):
        assert path in paths
    assert WEB_REFACTOR_PHASE >= 5

    root = files("persona_dock")
    html = root.joinpath("web/static/index.html").read_text(encoding="utf-8")
    css = root.joinpath("web/static/deployments.css").read_text(encoding="utf-8")
    javascript = root.joinpath("web/static/deployments.js").read_text(encoding="utf-8")
    api_source = root.joinpath("web/deployment_api.py").read_text(encoding="utf-8")

    assert 'href="/assets/deployments.css"' in html
    assert 'src="/assets/deployments.js"' in html
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert "localStorage" not in javascript
    assert "pendingPlan" in javascript
    assert "confirmation_token: value.token" in javascript
    assert 'input={"plan_id": request.plan_id}' in api_source
    assert '"confirmation_token": request.confirmation_token' not in api_source
