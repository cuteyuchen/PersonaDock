from __future__ import annotations

import platform
import sys
from typing import Any

from persona_dock import __version__
from persona_dock.adapters.hermes import HermesAdapter
from persona_dock.adapters.legacy_filesystem import LegacyFilesystemAdapter


def doctor_report() -> dict[str, Any]:
    adapters = [
        HermesAdapter().doctor(),
        LegacyFilesystemAdapter("openclaw").doctor(),
        LegacyFilesystemAdapter("generic").doctor(),
    ]
    return {
        "personadock_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "executable": sys.executable,
        "web": {
            "default_host": "127.0.0.1",
            "default_port": 8732,
            "remote_requires_token": True,
        },
        "adapters": [result.to_dict() for result in adapters],
    }


def render_doctor(report: dict[str, Any]) -> str:
    lines = [
        f"PersonaDock {report['personadock_version']}",
        f"Platform: {report['platform']} ({report['machine']})",
        f"Python: {report['python_version']}",
        "",
        "Adapters:",
    ]
    for adapter in report["adapters"]:
        lines.append(f"- {adapter['adapter']}: {adapter['status']}")
        lines.append(f"  {adapter['message']}")
        if adapter.get("executable"):
            lines.append(f"  executable: {adapter['executable']}")
        if adapter.get("version"):
            lines.append(f"  version: {adapter['version']}")
        target_path = adapter.get("details", {}).get("target_path")
        if target_path:
            lines.append(f"  target: {target_path}")
        if adapter.get("details", {}).get("native"):
            lines.append("  deployment: native Hermes Profile Distribution")
    return "\n".join(lines)
