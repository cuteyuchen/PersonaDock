from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_vue_phase_six_routes_ai_studio_and_provider_settings() -> None:
    router = (FRONTEND / "src/router/index.ts").read_text(encoding="utf-8")
    assert "AIStudioView" in router
    assert "/settings/providers" in router
    assert "legacyHash: '#/ai-studio'" not in router


def test_vue_phase_six_preserves_vault_and_apply_contracts() -> None:
    api = (FRONTEND / "src/api/operations.ts").read_text(encoding="utf-8")
    view = (FRONTEND / "src/views/AIStudioView.vue").read_text(encoding="utf-8")

    assert "/api/v1/ai/providers" in api
    assert "/api/v1/ai/generations" in api
    assert "confirmation: 'APPLY'" in api
    assert "不会回显 Secret" in view
    assert "不保存 instruction 或 evidence 原文" in view
    assert "Refine 的 base Revision 已变化时" in view
    assert "Canonical、semantic diff、risk、validation、tests 和 compile preview" in view
