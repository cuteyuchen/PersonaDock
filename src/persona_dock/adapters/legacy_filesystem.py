from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from persona_dock.adapters.base import AdapterCapabilities, AdapterDoctorResult, PersonaAdapter
from persona_dock.deployment.plans import build_deployment_plan
from persona_dock.targeting import TargetResolutionError, detect_local_target


class LegacyFilesystemAdapter(PersonaAdapter):
    """Compatibility adapter used until native platform adapters are available."""

    name = "legacy-filesystem"

    def __init__(self, target: str) -> None:
        if target not in {"hermes", "openclaw", "generic"}:
            raise ValueError(f"unsupported target: {target}")
        self.target = target

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            discovery=False,
            native_deployment=False,
            filesystem_deployment=True,
            memory_pull=False,
            memory_push=False,
            session_summary_pull=False,
            raw_session_import=False,
            docker=True,
        )

    def _version(self, executable: str | None) -> str | None:
        if not executable:
            return None
        try:
            result = subprocess.run(
                [executable, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = result.stdout.strip() or result.stderr.strip()
        return text.splitlines()[0] if text else None

    def doctor(self) -> AdapterDoctorResult:
        executable = shutil.which(self.target) if self.target != "generic" else None
        try:
            detected = detect_local_target(self.target)
            return AdapterDoctorResult(
                adapter=self.target,
                available=True,
                executable=executable,
                version=self._version(executable),
                status="ready",
                message=f"Safe legacy target detected at {detected.path}",
                capabilities=self.capabilities,
                details={
                    "target_path": str(detected.path),
                    "target_source": detected.source,
                    "confidence": detected.confidence,
                    "evidence": list(detected.evidence),
                    "native_adapter": False,
                },
            )
        except TargetResolutionError as error:
            return AdapterDoctorResult(
                adapter=self.target,
                available=bool(executable) or self.target == "generic",
                executable=executable,
                version=self._version(executable),
                status="needs-path" if self.target != "generic" else "ready",
                message=str(error),
                capabilities=self.capabilities,
                details={"native_adapter": False},
            )

    def plan_deployment(
        self,
        package: str,
        *,
        destination: str | None = None,
        container: str | None = None,
    ) -> dict[str, Any]:
        return build_deployment_plan(
            Path(package),
            self.target,
            destination,
            container,
        ).to_dict()
