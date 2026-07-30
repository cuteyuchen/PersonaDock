from __future__ import annotations

import json
from pathlib import Path

from persona_dock.web import create_app
from persona_dock.web.version import WEB_FRONTEND, WEB_FRONTEND_MIGRATION_PHASE


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_vue_preview_routes_are_registered() -> None:
    paths = {route.path for route in create_app().routes}
    assert "/vue" in paths
    assert "/assets/vue/{asset_path:path}" in paths
    assert WEB_FRONTEND == "vue3-shadcn-vue"
    assert WEB_FRONTEND_MIGRATION_PHASE >= 1


def test_vue_project_uses_vite_typescript_and_shadcn_vue() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    components = json.loads((FRONTEND / "components.json").read_text(encoding="utf-8"))

    assert "vue" in package["dependencies"]
    assert "pinia" in package["dependencies"]
    assert "@tanstack/vue-query" in package["dependencies"]
    assert "reka-ui" in package["dependencies"]
    assert "shadcn-vue" in package["devDependencies"]
    assert "vite" in package["devDependencies"]
    assert "typescript" in package["devDependencies"]
    assert components["style"] == "new-york"
    assert components["tailwind"]["baseColor"] == "zinc"


def test_vue_source_keeps_restrained_desktop_tool_visuals() -> None:
    css = (FRONTEND / "src/styles/index.css").read_text(encoding="utf-8")
    shell = (FRONTEND / "src/components/layout/AppShell.vue").read_text(encoding="utf-8")
    dashboard = (FRONTEND / "src/views/DashboardView.vue").read_text(encoding="utf-8")

    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert "cdn" not in (FRONTEND / "index.html").read_text(encoding="utf-8").lower()
    assert "旧界面兼容入口" in shell
    assert 'href="/legacy"' in shell
    assert "本地人格控制面" in dashboard
    assert "chat-bubble" not in shell


def test_vite_build_targets_python_package_data() -> None:
    config = (FRONTEND / "vite.config.ts").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/release-bundle.yml").read_text(encoding="utf-8")

    assert "../src/persona_dock/web/static/vue" in config
    assert '"web/static/vue/*"' in pyproject
    assert "Type-check Vue frontend" in workflow
    assert "Test Vue frontend" in workflow
    assert "Build embedded Vue frontend" in workflow
