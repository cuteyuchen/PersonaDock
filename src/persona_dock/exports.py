from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from persona_dock.compiler import compile_project
from persona_dock.io import dump_yaml
from persona_dock.packaging import pack_project
from persona_dock.registry.database import registry_root
from persona_dock.registry.service import RegistryService


EXPORT_FORMATS = {"personapack", "hermes-profile", "openclaw-workspace"}


@dataclass(frozen=True)
class ExportResult:
    persona_id: str
    version: str
    format: str
    path: str
    includes_memory: bool
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _remove_memory(target: Path) -> None:
    for relative in ("memory", "MEMORY.md", "USER.md"):
        path = target / relative
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _zip_directory(source: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() != ".zip":
        output = output.with_suffix(".zip")
    temporary_base = output.with_suffix("")
    archive = Path(shutil.make_archive(str(temporary_base), "zip", root_dir=source))
    if archive != output:
        if output.exists():
            output.unlink()
        archive.replace(output)
    return output


def export_registered_persona(
    persona_id: str,
    export_format: str,
    *,
    output: str | Path | None = None,
    include_memory: bool = False,
    registry: RegistryService | None = None,
) -> ExportResult:
    if export_format not in EXPORT_FORMATS:
        raise ValueError(
            f"unsupported export format: {export_format}; choose from {', '.join(sorted(EXPORT_FORMATS))}"
        )
    service = registry or RegistryService()
    persona = service.get_persona(persona_id)
    if persona is None:
        raise ValueError(f"persona is not registered: {persona_id}")
    if not persona.source_path:
        raise ValueError(f"persona has no source project: {persona_id}")
    source = Path(persona.source_path).expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(source)

    export_root = registry_root() / "exports" / persona_id / persona.version
    export_root.mkdir(parents=True, exist_ok=True)
    created_at = _utc_now()

    if export_format == "personapack":
        destination = Path(output).expanduser().resolve() if output else export_root / f"{persona_id}-{persona.version}.personapack"
        result_path = pack_project(source, destination)
    else:
        target_name = "hermes" if export_format == "hermes-profile" else "openclaw"
        default_name = f"{persona_id}-{persona.version}-{export_format}.zip"
        destination = Path(output).expanduser().resolve() if output else export_root / default_name
        with tempfile.TemporaryDirectory(prefix="personadock-export-") as temporary:
            temporary_root = Path(temporary)
            build = compile_project(source, temporary_root / "build", [target_name])
            native_source = build / "targets" / target_name
            native = temporary_root / f"{persona_id}-{export_format}"
            shutil.copytree(native_source, native)
            if not include_memory:
                _remove_memory(native)

            if export_format == "hermes-profile":
                distribution = {
                    "name": persona_id,
                    "version": persona.version,
                    "description": persona.summary,
                    "source": "PersonaDock",
                    "distribution_owned": [
                        "SOUL.md",
                        *[
                            path.relative_to(native).as_posix()
                            for path in sorted((native / "skills").rglob("*"))
                            if path.is_file()
                        ],
                    ],
                    "privacy": {
                        "credentials_included": False,
                        "sessions_included": False,
                        "memory_included": include_memory,
                    },
                }
                (native / "distribution.yaml").write_text(dump_yaml(distribution), encoding="utf-8")
            else:
                manifest = {
                    "format": "personadock-openclaw-workspace-overlay",
                    "format_version": 1,
                    "persona_id": persona_id,
                    "persona_version": persona.version,
                    "created_at": created_at,
                    "owned_paths": [
                        path.relative_to(native).as_posix()
                        for path in sorted(native.rglob("*"))
                        if path.is_file()
                    ],
                    "preserve": [
                        "AGENTS.md",
                        "USER.md",
                        "TOOLS.md",
                        "sessions",
                        "credentials",
                        "platform-local skills",
                    ],
                    "privacy": {
                        "credentials_included": False,
                        "sessions_included": False,
                        "memory_included": include_memory,
                    },
                }
                (native / "personadock-manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            result_path = _zip_directory(native, destination)

    service.journal(
        "persona-exported",
        persona_id=persona_id,
        payload={
            "format": export_format,
            "path": str(result_path),
            "include_memory": include_memory,
            "created_at": created_at,
        },
    )
    return ExportResult(
        persona_id=persona_id,
        version=persona.version,
        format=export_format,
        path=str(result_path),
        includes_memory=include_memory,
        created_at=created_at,
    )
