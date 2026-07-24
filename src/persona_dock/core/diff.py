from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from persona_dock.core.models import behavior_index, boundary_index, load_canonical_persona


@dataclass(frozen=True)
class FieldChange:
    path: str
    before: Any
    after: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersonaDiff:
    before: str
    after: str
    added_behaviors: tuple[str, ...]
    removed_behaviors: tuple[str, ...]
    changed_behaviors: tuple[str, ...]
    added_boundaries: tuple[str, ...]
    removed_boundaries: tuple[str, ...]
    changed_boundaries: tuple[str, ...]
    field_changes: tuple[FieldChange, ...]

    @property
    def changed(self) -> bool:
        return any(
            (
                self.added_behaviors,
                self.removed_behaviors,
                self.changed_behaviors,
                self.added_boundaries,
                self.removed_boundaries,
                self.changed_boundaries,
                self.field_changes,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["field_changes"] = [item.to_dict() for item in self.field_changes]
        value["changed"] = self.changed
        return value


def _changed_keys(before: dict[str, Any], after: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    before_keys = set(before)
    after_keys = set(after)
    added = tuple(sorted(after_keys - before_keys))
    removed = tuple(sorted(before_keys - after_keys))
    changed = tuple(sorted(key for key in before_keys & after_keys if before[key] != after[key]))
    return added, removed, changed


def diff_personas(before_root: Path, after_root: Path) -> PersonaDiff:
    before = load_canonical_persona(before_root)
    after = load_canonical_persona(after_root)
    before_behaviors = behavior_index(before)
    after_behaviors = behavior_index(after)
    added_behaviors, removed_behaviors, changed_behaviors = _changed_keys(
        before_behaviors, after_behaviors
    )
    before_boundaries = boundary_index(before)
    after_boundaries = boundary_index(after)
    added_boundaries, removed_boundaries, changed_boundaries = _changed_keys(
        before_boundaries, after_boundaries
    )

    fields = [
        ("version", before.get("version"), after.get("version")),
        ("name", before.get("name"), after.get("name")),
        ("summary", before.get("summary"), after.get("summary")),
        ("identity.statement", before["identity"].get("statement"), after["identity"].get("statement")),
        ("identity.core_traits", before["identity"].get("core_traits"), after["identity"].get("core_traits")),
        ("voice.style", before["voice"].get("style"), after["voice"].get("style")),
        ("voice.principles", before["voice"].get("principles"), after["voice"].get("principles")),
        ("budgets", before.get("budgets"), after.get("budgets")),
        ("memory", before.get("memory"), after.get("memory")),
        ("targets", before.get("targets"), after.get("targets")),
    ]
    field_changes = tuple(
        FieldChange(path=path, before=old, after=new)
        for path, old, new in fields
        if old != new
    )
    return PersonaDiff(
        before=str(Path(before_root).expanduser().resolve()),
        after=str(Path(after_root).expanduser().resolve()),
        added_behaviors=added_behaviors,
        removed_behaviors=removed_behaviors,
        changed_behaviors=changed_behaviors,
        added_boundaries=added_boundaries,
        removed_boundaries=removed_boundaries,
        changed_boundaries=changed_boundaries,
        field_changes=field_changes,
    )
