from __future__ import annotations

from pathlib import Path
from typing import Any

from persona_dock.io import load_yaml
from persona_dock.project import PROJECT_FILE, find_project, init_project, validate_project
from persona_dock.registry import RegistryService


class PersonaApplicationService:
    """Create, register and query Persona projects through one shared service."""

    def __init__(self, registry: RegistryService | None = None) -> None:
        self.registry = registry or RegistryService()

    def _register(self, root: Path, *, event_type: str) -> dict[str, Any]:
        value = load_yaml(root / PROJECT_FILE)
        record = self.registry.register_persona(
            persona_id=str(value["id"]),
            name=str(value["name"]),
            version=str(value["version"]),
            source_path=root,
            schema_version=int(value.get("schema_version", 2)),
            summary=str(value.get("summary", "")),
        )
        self.registry.journal(
            event_type,
            persona_id=record.id,
            payload={
                "source_path": str(root),
                "schema_version": record.schema_version,
                "version": record.version,
            },
        )
        return record.to_dict()

    def create(
        self,
        destination: str | Path,
        *,
        persona_id: str,
        name: str,
        locale: str = "zh-CN",
        force: bool = False,
    ) -> dict[str, Any]:
        root = init_project(
            Path(destination),
            persona_id,
            name,
            locale,
            force,
            schema_version=3,
        )
        record = self._register(root, event_type="persona-created")
        return {"project": str(root), "persona": record}

    def register(self, project: str | Path) -> dict[str, Any]:
        root = find_project(Path(project))
        errors = validate_project(root)
        if errors:
            raise ValueError("Persona project validation failed: " + "; ".join(errors))
        record = self._register(root, event_type="persona-registered")
        return {"project": str(root), "persona": record}

    def list(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self.registry.list_personas()]

    def get(self, persona_id: str) -> dict[str, Any] | None:
        record = self.registry.get_persona(persona_id)
        if record is None:
            return None
        return {
            **record.to_dict(),
            "bindings": [
                binding.to_dict() for binding in self.registry.list_bindings(persona_id)
            ],
        }


__all__ = ["PersonaApplicationService"]
