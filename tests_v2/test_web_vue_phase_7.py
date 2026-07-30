from __future__ import annotations

from pathlib import Path

from fastapi.responses import HTMLResponse

from persona_dock.web import create_app
from persona_dock.web.version import WEB_FRONTEND_MIGRATION_PHASE


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_vue_phase_seven_owns_root_and_keeps_one_legacy_entry() -> None:
    app = create_app()
    root_routes = [route for route in app.routes if getattr(route, "path", None) == "/"]
    assert len(root_routes) == 1
    assert root_routes[0].endpoint.__name__ == "vue_root"
    response = root_routes[0].endpoint()
    assert isinstance(response, HTMLResponse)
    assert "/assets/vue/app.js" in response.body.decode("utf-8")

    paths = {route.path for route in app.routes}
    assert "/vue" in paths
    assert "/legacy" in paths
    assert WEB_FRONTEND_MIGRATION_PHASE == 7


def test_vue_phase_seven_has_browser_accessibility_and_performance_gates() -> None:
    package = (FRONTEND / "package.json").read_text(encoding="utf-8")
    config = (FRONTEND / "playwright.config.ts").read_text(encoding="utf-8")
    e2e = (FRONTEND / "e2e/control-plane.spec.ts").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/release-bundle.yml").read_text(encoding="utf-8")
    router = (FRONTEND / "src/router/index.ts").read_text(encoding="utf-8")

    assert '"@playwright/test"' in package
    assert '"@axe-core/playwright"' in package
    assert "webServer" in config
    assert "AxeBuilder" in e2e
    assert "8 * 1024 * 1024" in e2e
    assert "Install Playwright Chromium" in workflow
    assert "Run Vue browser E2E" in workflow
    assert "PlaceholderView" not in router
