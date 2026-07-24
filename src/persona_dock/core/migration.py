from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from persona_dock.core.models import behavior_rule, normalize_canonical_persona
from persona_dock.io import dump_yaml, load_yaml
from persona_dock.project import PROJECT_FILE, find_project


@dataclass(frozen=True)
class MigrationResult:
    project: str
    from_schema: int
    to_schema: int
    backup: str | None
    changed: bool
    behavior_rules: int
    boundaries: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _rule_id(value: str, fallback: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def migrate_v2_value(value: dict[str, Any]) -> dict[str, Any]:
    if int(value.get("schema_version", 0)) != 2:
        raise ValueError("migrate_v2_value requires schema_version 2")
    soul = value.get("soul", {})
    triggers = [str(item) for item in soul.get("skill_triggers", [])]
    boundaries = [str(item) for item in soul.get("boundaries", [])]

    behaviors: list[dict[str, Any]] = []
    for index, trigger in enumerate(triggers, 1):
        behaviors.append(
            behavior_rule(
                rule_id=_rule_id(trigger, f"imported-behavior-{index:03d}"),
                intent="persona-skill-routing",
                conditions=[trigger],
                actions=["load_persona_skill", "apply_persona_rules"],
                constraints=["do_not_invent_memory"],
                priority="high" if index <= 2 else "medium",
                confidence="explicit",
                source_type="reviewed-existing",
                tests=["skill-routing"] if index == 1 else [],
            )
        )

    if not behaviors:
        behaviors.append(
            behavior_rule(
                rule_id="general-persona-response",
                intent="general",
                conditions=["persona expression is relevant"],
                actions=["apply stable identity and voice"],
                constraints=["do_not_invent_memory"],
                priority="medium",
                confidence="medium",
                source_type="safe-default",
                tests=["memory-honesty"],
            )
        )

    result = {
        "schema_version": 3,
        "id": value["id"],
        "version": value["version"],
        "name": value["name"],
        "locale": value["locale"],
        "summary": value["summary"],
        "identity": {
            "statement": soul.get("identity", ""),
            "core_traits": list(soul.get("core_traits", [])),
        },
        "voice": {
            "style": soul.get("voice", ""),
            "principles": [
                "保持稳定人格但不过度表演",
                "根据场景调整长度和情绪强度",
                "不照抄示例，提取表达规律",
            ],
        },
        "boundaries": [
            {
                "id": _rule_id(boundary, f"boundary-{index:03d}"),
                "rule": boundary,
                "priority": "critical" if "不得" in boundary or "不虚构" in boundary else "high",
                "source_type": "reviewed-existing",
            }
            for index, boundary in enumerate(boundaries, 1)
        ],
        "behaviors": behaviors,
        "budgets": {
            "target_chars": int(soul.get("target_chars", 1800)),
            "hard_limit_chars": int(soul.get("hard_limit_chars", 2800)),
        },
        "skill": dict(value.get("skill", {})),
        "memory": dict(value.get("memory", {})),
        "targets": list(value.get("targets", [])),
        "migration": {
            "from_schema": 2,
            "migrated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "notes": [
                "v2 skill_triggers were converted to structured behavior rules",
                "v2 boundaries were assigned stable IDs",
                "behavior evidence remains empty until reviewed",
            ],
        },
    }
    return normalize_canonical_persona(result)


def migrate_project_to_v3(
    root: Path,
    *,
    output: Path | None = None,
    in_place: bool = False,
    backup: bool = True,
) -> MigrationResult:
    root = find_project(root)
    current_path = root / PROJECT_FILE
    value = load_yaml(current_path)
    schema = int(value.get("schema_version", 0))
    if schema == 3:
        return MigrationResult(
            project=str(root),
            from_schema=3,
            to_schema=3,
            backup=None,
            changed=False,
            behavior_rules=len(value.get("behaviors", [])),
            boundaries=len(value.get("boundaries", [])),
        )
    if schema != 2:
        raise ValueError(f"unsupported source schema: {schema}")
    if output and in_place:
        raise ValueError("choose either --output or --in-place")

    migrated = migrate_v2_value(value)
    backup_path: Path | None = None

    if in_place:
        destination = root
        if backup:
            backup_path = root / ".personadock" / "migrations" / f"schema-v2-{_timestamp()}"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(root, backup_path, ignore=shutil.ignore_patterns(".personadock"))
    else:
        destination = (output or root.parent / f"{root.name}-v3").expanduser().resolve()
        if destination.exists():
            if any(destination.iterdir()):
                raise FileExistsError(f"migration destination is not empty: {destination}")
        else:
            destination.mkdir(parents=True)
        for child in root.iterdir():
            if child.name == ".personadock":
                continue
            target = destination / child.name
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=True)
            else:
                shutil.copy2(child, target)

    (destination / PROJECT_FILE).write_text(dump_yaml(migrated), encoding="utf-8")
    migration_report = {
        "format": "personadock-schema-migration",
        "from_schema": 2,
        "to_schema": 3,
        "source": str(root),
        "destination": str(destination),
        "backup": str(backup_path) if backup_path else None,
        "behavior_rules": len(migrated["behaviors"]),
        "boundaries": len(migrated["boundaries"]),
    }
    report_path = destination / ".personadock" / "migration-v2-v3.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(migration_report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return MigrationResult(
        project=str(destination),
        from_schema=2,
        to_schema=3,
        backup=str(backup_path) if backup_path else None,
        changed=True,
        behavior_rules=len(migrated["behaviors"]),
        boundaries=len(migrated["boundaries"]),
    )
