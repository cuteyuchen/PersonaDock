from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def project_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def package_version() -> str:
    source = (ROOT / "src/persona_dock/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    if match is None:
        raise RuntimeError("src/persona_dock/__init__.py does not define __version__")
    return match.group(1)


def frontend_version() -> str:
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    return str(package["version"])


def changelog_contains(version: str) -> bool:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.search(rf"^##\s+{re.escape(version)}(?:\s+—|\s+-|$)", changelog, re.MULTILINE) is not None


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify PersonaDock release version metadata.")
    parser.add_argument("--tag", help="Optional Git tag, for example v1.1.0")
    arguments = parser.parse_args()

    version = project_version()
    values = {
        "pyproject.toml": version,
        "src/persona_dock/__init__.py": package_version(),
        "frontend/package.json": frontend_version(),
    }
    mismatches = {path: value for path, value in values.items() if value != version}
    if mismatches:
        details = ", ".join(f"{path}={value}" for path, value in mismatches.items())
        raise SystemExit(f"release version mismatch: expected {version}; {details}")

    if not changelog_contains(version):
        raise SystemExit(f"CHANGELOG.md has no release heading for {version}")

    if arguments.tag is not None and arguments.tag != f"v{version}":
        raise SystemExit(f"tag mismatch: expected v{version}, got {arguments.tag}")

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
