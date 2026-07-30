from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_vue_phase_five_routes_native_governance_pages() -> None:
    router = (FRONTEND / "src/router/index.ts").read_text(encoding="utf-8")
    assert "GovernanceWorkspaceView" in router
    assert "legacyHash: '#/memory'" not in router
    assert "legacyHash: '#/sessions'" not in router


def test_vue_phase_five_preserves_review_and_apply_boundaries() -> None:
    api = (FRONTEND / "src/api/operations.ts").read_text(encoding="utf-8")
    view = (FRONTEND / "src/views/GovernanceWorkspaceView.vue").read_text(encoding="utf-8")

    assert "/api/v1/governance/memory/" in api
    assert "/api/v1/governance/sessions/" in api
    assert "/api/sync/conflicts/" in api
    assert "confirmed: true" in api
    assert "不传播原始 Session" in view or "不同步原始 Session" in view
    assert "显式确认并应用" in view
    assert "只传播经过过滤、脱敏和审核的摘要" in view
