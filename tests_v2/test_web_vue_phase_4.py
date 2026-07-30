from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_vue_phase_four_routes_native_runtime_and_deployment_pages() -> None:
    router = (FRONTEND / "src/router/index.ts").read_text(encoding="utf-8")
    assert "/runtimes/:runtimeId" in router
    assert "DeploymentWorkspaceView" in router
    assert "legacyHash: '#/deployments'" not in router


def test_vue_phase_four_preserves_plan_apply_security() -> None:
    api = (FRONTEND / "src/api/operations.ts").read_text(encoding="utf-8")
    view = (FRONTEND / "src/views/DeploymentWorkspaceView.vue").read_text(encoding="utf-8")

    assert "/api/v1/deployment-plans" in api
    assert "confirmation_token" in api
    assert "confirmation: 'ROLLBACK'" in api
    assert "一次性确认令牌" in view
    assert "若发生变化返回 409" in view
    assert "adoptionPreview" in view
    assert "确认接管" in view
