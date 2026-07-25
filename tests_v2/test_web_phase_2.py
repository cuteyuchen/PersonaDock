from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest

from persona_dock.application import PersonaApplicationService
from persona_dock.registry import RegistryService
from persona_dock.registry.database import RegistryDatabase
from persona_dock.web import create_app
from persona_dock.web.capabilities import CAPABILITIES, validate_capabilities
from persona_dock.web.paths import PersonaPathPolicy, WebPathError


def _service(tmp_path: Path) -> PersonaApplicationService:
    database = RegistryDatabase(tmp_path / "registry.db")
    return PersonaApplicationService(RegistryService(database))


def test_persona_application_service_creates_v3_and_registers(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.create(
        tmp_path / "personas" / "xiaoyou",
        persona_id="xiaoyou",
        name="小柚",
        locale="zh-CN",
    )

    project = Path(result["project"])
    assert project.is_dir()
    assert (project / "companion.yaml").is_file()
    assert result["persona"]["id"] == "xiaoyou"
    assert result["persona"]["schema_version"] == 3
    assert service.get("xiaoyou") is not None

    second = _service(tmp_path / "other")
    registered = second.register(project)
    assert registered["persona"]["id"] == "xiaoyou"
    assert registered["project"] == str(project.resolve())


def test_persona_application_service_rejects_invalid_registration(tmp_path: Path) -> None:
    service = _service(tmp_path)
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    with pytest.raises(FileNotFoundError):
        service.register(invalid)


def test_web_persona_path_policy_confines_create_and_register(tmp_path: Path) -> None:
    root = (tmp_path / "personas").resolve()
    root.mkdir()
    policy = PersonaPathPolicy((root,))

    assert policy.resolve_new("xiaoyou") == root / "xiaoyou"
    assert policy.resolve_new("group/xiaoyou") == root / "group" / "xiaoyou"

    existing = root / "existing"
    existing.mkdir()
    assert policy.resolve_existing(str(existing)) == existing

    with pytest.raises(WebPathError, match="relative"):
        policy.resolve_new(str(tmp_path / "absolute"))
    with pytest.raises(WebPathError, match="unsafe"):
        policy.resolve_new("../outside")
    with pytest.raises(WebPathError, match="outside"):
        policy.resolve_existing(str(tmp_path / "outside"))


def test_phase_two_capabilities_are_ready() -> None:
    assert validate_capabilities() == []
    values = {item.id: item for item in CAPABILITIES}
    for capability_id in (
        "persona.init",
        "persona.list",
        "persona.show",
        "persona.register",
        "persona.export",
        "runtime.discover",
        "runtime.instances",
        "runtime.adopt",
    ):
        assert values[capability_id].status == "ready"


def test_phase_two_routes_and_lifecycle_asset_are_registered() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    for path in (
        "/api/v1/persona-roots",
        "/api/v1/personas",
        "/api/v1/personas/{persona_id}",
        "/api/v1/personas/register",
        "/api/v1/runtimes/discover",
        "/api/v1/adoptions/preview",
        "/api/v1/adoptions",
        "/api/v1/personas/{persona_id}/exports",
        "/assets/lifecycle.js",
    ):
        assert path in paths


def test_phase_two_shell_loads_safe_lifecycle_workflows() -> None:
    root = files("persona_dock.web.static")
    html = root.joinpath("index.html").read_text(encoding="utf-8")
    javascript = root.joinpath("lifecycle.js").read_text(encoding="utf-8")

    assert "PersonaDock Control Plane" in html
    assert 'src="/assets/lifecycle.js"' in html
    assert "/api/v1/persona-roots" in javascript
    assert "/api/v1/personas/register" in javascript
    assert "/api/v1/runtimes/discover" in javascript
    assert "/api/v1/adoptions" in javascript
    assert "PERSONADOCK_PERSONA_ROOTS" not in javascript
    assert "subprocess" not in javascript
