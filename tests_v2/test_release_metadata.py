from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_are_consistent() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    frontend = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    package_source = (ROOT / "src/persona_dock/__init__.py").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    version = pyproject["project"]["version"]
    assert version == "1.1.0"
    assert f'__version__ = "{version}"' in package_source
    assert frontend["version"] == version
    assert f"## {version} —" in changelog


def test_release_workflows_package_validated_vue_assets() -> None:
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    bundle = (ROOT / ".github/workflows/release-bundle.yml").read_text(encoding="utf-8")

    # Parse both files to catch malformed YAML in addition to string-level contracts.
    assert isinstance(yaml.safe_load(release), dict)
    assert isinstance(yaml.safe_load(bundle), dict)

    for source in (release, bundle):
        assert "scripts/check_release_version.py" in source
        assert "pnpm --dir frontend build" in source
        assert "scripts/verify_release_binary.py" in source
        assert "scripts/verify_vue_binary.py" in source

    assert "release-vue-assets" in release
    assert "actions/download-artifact@v4" in release
    assert "scripts/extract_release_notes.py" in release
    assert "persona-demo-${{ steps.version.outputs.package_version }}.personapack" in bundle
    assert "persona-dock-${{ steps.version.outputs.package_version }}" in bundle
