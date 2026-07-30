from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_vue_phase_three_routes_use_native_workspace() -> None:
    router = (FRONTEND / "src/router/index.ts").read_text(encoding="utf-8")
    for route in ("/packages", "/backups", "/character-cards", "/adapters"):
        assert route in router
    assert "ArtifactWorkspaceView" in router
    assert "legacyHash: '#/packages'" not in router
    assert "legacyHash: '#/backups'" not in router


def test_vue_phase_three_covers_artifact_security_contracts() -> None:
    api = (FRONTEND / "src/api/operations.ts").read_text(encoding="utf-8")
    view = (FRONTEND / "src/views/ArtifactWorkspaceView.vue").read_text(encoding="utf-8")

    for endpoint in (
        "/api/v1/personas/${encodeURIComponent(personaId)}/builds",
        "/api/v1/trust/signatures",
        "/api/v1/trust/verify",
        "/api/v1/backups/restore",
        "/api/v1/character-cards/import",
        "/api/v1/skills/install",
    ):
        assert endpoint in api
    assert "password" in view
    assert "sessionStorage" not in view
    assert "私钥永不" in view
    assert "备份密码和部署确认令牌不会写入 Job" in view
