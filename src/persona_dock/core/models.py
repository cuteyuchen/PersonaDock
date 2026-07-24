from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from persona_dock.io import load_yaml
from persona_dock.project import PROJECT_FILE, find_project


SCHEMA_VERSION = 3
BEHAVIOR_PRIORITIES = {"low", "medium", "high", "critical"}
CONFIDENCE_LEVELS = {"explicit", "high", "medium", "low"}
SOURCE_TYPES = {
    "explicit-design",
    "observed-evidence",
    "reviewed-existing",
    "safe-default",
}


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def behavior_rule(
    *,
    rule_id: str,
    intent: str,
    conditions: list[str],
    actions: list[str],
    constraints: list[str],
    priority: str,
    confidence: str,
    source_type: str,
    evidence: list[str] | None = None,
    tests: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "trigger": {"intent": intent, "conditions": conditions},
        "behavior": actions,
        "constraints": constraints,
        "priority": priority,
        "confidence": confidence,
        "source_type": source_type,
        "evidence": evidence or [],
        "tests": tests or [],
    }


def normalize_canonical_persona(value: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, compiler-friendly copy of a v3 persona."""
    result = copy.deepcopy(value)
    if int(result.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError("Canonical Persona must use schema_version 3")

    result.setdefault("identity", {})
    result["identity"].setdefault("statement", "")
    result["identity"].setdefault("core_traits", [])
    result.setdefault("voice", {})
    result["voice"].setdefault("style", "")
    result["voice"].setdefault("principles", [])
    result.setdefault("boundaries", [])
    result.setdefault("behaviors", [])
    result.setdefault("budgets", {"target_chars": 1800, "hard_limit_chars": 2800})
    result.setdefault("memory", {})
    result["memory"].setdefault("enabled", True)
    result["memory"].setdefault("private_by_default", True)
    result["memory"].setdefault("bundle_policy", "reviewed")
    result["memory"].setdefault("never_invent", True)
    result.setdefault("targets", ["hermes", "openclaw", "generic"])

    result["identity"]["core_traits"] = list(dict.fromkeys(result["identity"]["core_traits"]))
    result["voice"]["principles"] = list(dict.fromkeys(result["voice"]["principles"]))

    normalized_boundaries: list[dict[str, Any]] = []
    seen_boundary_ids: set[str] = set()
    for index, boundary in enumerate(result["boundaries"], 1):
        if isinstance(boundary, str):
            boundary = {
                "id": f"boundary-{index:03d}",
                "rule": boundary,
                "priority": "high",
                "source_type": "reviewed-existing",
            }
        boundary = dict(boundary)
        boundary.setdefault("id", f"boundary-{index:03d}")
        boundary["id"] = _slug(str(boundary["id"]), f"boundary-{index:03d}")
        if boundary["id"] in seen_boundary_ids:
            boundary["id"] = f"{boundary['id']}-{index}"
        seen_boundary_ids.add(boundary["id"])
        boundary.setdefault("priority", "high")
        boundary.setdefault("source_type", "reviewed-existing")
        normalized_boundaries.append(boundary)
    result["boundaries"] = normalized_boundaries

    normalized_behaviors: list[dict[str, Any]] = []
    seen_behavior_ids: set[str] = set()
    for index, behavior in enumerate(result["behaviors"], 1):
        item = dict(behavior)
        item.setdefault("id", f"behavior-{index:03d}")
        item["id"] = _slug(str(item["id"]), f"behavior-{index:03d}")
        if item["id"] in seen_behavior_ids:
            item["id"] = f"{item['id']}-{index}"
        seen_behavior_ids.add(item["id"])
        item.setdefault("trigger", {"intent": "general", "conditions": []})
        item["trigger"].setdefault("intent", "general")
        item["trigger"].setdefault("conditions", [])
        item.setdefault("behavior", [])
        item.setdefault("constraints", [])
        item.setdefault("priority", "medium")
        item.setdefault("confidence", "medium")
        item.setdefault("source_type", "reviewed-existing")
        item.setdefault("evidence", [])
        item.setdefault("tests", [])
        normalized_behaviors.append(item)
    result["behaviors"] = normalized_behaviors
    return result


def load_canonical_persona(root: Path) -> dict[str, Any]:
    root = find_project(root)
    value = load_yaml(root / PROJECT_FILE)
    if int(value.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError(
            f"{PROJECT_FILE} uses schema {value.get('schema_version')}; run `personadock migrate`"
        )
    return normalize_canonical_persona(value)


def behavior_index(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized = normalize_canonical_persona(value)
    return {item["id"]: item for item in normalized["behaviors"]}


def boundary_index(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized = normalize_canonical_persona(value)
    return {item["id"]: item for item in normalized["boundaries"]}
