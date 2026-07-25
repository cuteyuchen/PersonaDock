from __future__ import annotations

import os
from pathlib import Path

from persona_dock.registry.database import registry_root


class WebPathError(ValueError):
    pass


def configured_persona_roots() -> tuple[Path, ...]:
    configured = os.environ.get("PERSONADOCK_PERSONA_ROOTS", "")
    values = [item for item in configured.split(os.pathsep) if item.strip()]
    roots = [Path(item).expanduser().resolve() for item in values]
    default = (registry_root() / "personas").resolve()
    if default not in roots:
        roots.insert(0, default)
    return tuple(dict.fromkeys(roots))


class PersonaPathPolicy:
    def __init__(self, roots: tuple[Path, ...] | None = None) -> None:
        self.roots = roots or configured_persona_roots()
        if not self.roots:
            raise WebPathError("at least one Persona workspace root is required")

    @property
    def default_root(self) -> Path:
        return self.roots[0]

    def resolve_new(self, relative_path: str) -> Path:
        candidate = Path(relative_path.strip())
        if not relative_path.strip():
            raise WebPathError("Persona folder is required")
        if candidate.is_absolute():
            raise WebPathError("Web Persona folder must be relative to the configured root")
        if any(part in {"", ".", ".."} for part in candidate.parts):
            raise WebPathError("Persona folder contains an unsafe path segment")
        resolved = (self.default_root / candidate).resolve()
        self._require_allowed(resolved)
        return resolved

    def resolve_existing(self, value: str) -> Path:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self.default_root / candidate
        resolved = candidate.resolve()
        self._require_allowed(resolved)
        return resolved

    def _require_allowed(self, path: Path) -> None:
        for root in self.roots:
            try:
                path.relative_to(root)
                return
            except ValueError:
                continue
        allowed = ", ".join(str(item) for item in self.roots)
        raise WebPathError(f"path is outside configured Persona roots: {allowed}")

    def to_dict(self) -> dict[str, object]:
        return {
            "default_root": str(self.default_root),
            "roots": [str(item) for item in self.roots],
            "environment": "PERSONADOCK_PERSONA_ROOTS",
        }


__all__ = [
    "PersonaPathPolicy",
    "WebPathError",
    "configured_persona_roots",
]
