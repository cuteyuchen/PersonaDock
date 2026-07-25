from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any


SENSITIVITY_LEVELS = ("public", "internal", "private", "restricted")
SENSITIVITY_RANK = {value: index for index, value in enumerate(SENSITIVITY_LEVELS)}
MEMORY_STATUSES = ("pending", "approved", "rejected", "superseded")
CONFLICT_STATUSES = ("pending", "resolved")


DEFAULT_SYNC_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "mode": "review",
    "pull": {
        "enabled": True,
        "adapters": ["hermes", "openclaw"],
    },
    "push": {
        "enabled": True,
        "adapters": ["hermes", "openclaw"],
        "reviewed_only": True,
        "echo_to_source": False,
    },
    "auto_approve": {
        "enabled": False,
        "source_adapters": [],
        "memory_types": [],
        "max_sensitivity": "internal",
    },
    "conflicts": {
        "strategy": "manual",
    },
    "definition_sync": {
        "push": "manual",
        "pull": "snapshot-review",
    },
    "session_summaries": {
        "mode": "review",
        "source_adapters": ["hermes", "openclaw"],
        "auto_approve": False,
        "max_sensitivity": "internal",
        "max_turns": 20,
        "include_pending_tasks": True,
        "include_decisions": True,
        "include_emotional_context": False,
        "raw_session_import": "preview-only",
        "include_system_messages": False,
        "include_tool_messages": False,
    },
}


@dataclass(frozen=True)
class SyncPolicyRecord:
    id: str
    persona_id: str
    config: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryItemRecord:
    id: str
    persona_id: str
    fingerprint: str
    memory_key: str
    memory_type: str
    summary: str
    sensitivity: str
    sync_scope: str
    status: str
    source_adapter: str | None
    source_runtime_instance_id: str | None
    source_record_id: str | None
    source_path: str | None
    metadata: dict[str, Any]
    reviewed_at: str | None
    reviewed_by: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SyncConflictRecord:
    id: str
    persona_id: str
    candidate_id: str
    existing_item_id: str | None
    conflict_type: str
    status: str
    resolution: str | None
    details: dict[str, Any]
    created_at: str
    resolved_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SyncPlan:
    id: str
    persona_id: str
    policy: dict[str, Any]
    definition_actions: tuple[dict[str, Any], ...]
    memory_actions: tuple[dict[str, Any], ...]
    skipped: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "definition_actions": list(self.definition_actions),
            "memory_actions": list(self.memory_actions),
            "skipped": list(self.skipped),
            "conflicts": list(self.conflicts),
            "warnings": list(self.warnings),
        }


def deep_merge_policy(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge_policy(result[key], value)
        else:
            result[key] = value
    return result


def validate_policy(config: dict[str, Any]) -> dict[str, Any]:
    value = deep_merge_policy(DEFAULT_SYNC_POLICY, config)
    if value.get("schema_version") != 1:
        raise ValueError("sync policy schema_version must be 1")
    if value.get("mode") not in {"review", "automatic", "disabled"}:
        raise ValueError("sync policy mode must be review, automatic, or disabled")
    for direction in ("pull", "push"):
        section = value.get(direction)
        if not isinstance(section, dict):
            raise ValueError(f"sync policy {direction} must be an object")
        if not isinstance(section.get("enabled"), bool):
            raise ValueError(f"sync policy {direction}.enabled must be boolean")
        adapters = section.get("adapters", [])
        if not isinstance(adapters, list) or any(
            adapter not in {"hermes", "openclaw"} for adapter in adapters
        ):
            raise ValueError(f"sync policy {direction}.adapters contains an unsupported adapter")
    auto = value.get("auto_approve")
    if not isinstance(auto, dict) or not isinstance(auto.get("enabled"), bool):
        raise ValueError("sync policy auto_approve.enabled must be boolean")
    if auto.get("max_sensitivity") not in SENSITIVITY_RANK:
        raise ValueError(
            "sync policy auto_approve.max_sensitivity must be public, internal, private, or restricted"
        )
    strategy = value.get("conflicts", {}).get("strategy")
    if strategy not in {"manual", "keep-existing", "keep-both"}:
        raise ValueError("sync policy conflicts.strategy is unsupported")
    definition = value.get("definition_sync", {})
    if definition.get("push") not in {"manual", "disabled"}:
        raise ValueError("definition_sync.push must be manual or disabled")
    if definition.get("pull") not in {"snapshot-review", "disabled"}:
        raise ValueError("definition_sync.pull must be snapshot-review or disabled")

    sessions = value.get("session_summaries")
    if not isinstance(sessions, dict):
        raise ValueError("session_summaries must be an object")
    if sessions.get("mode") not in {"review", "automatic", "disabled"}:
        raise ValueError("session_summaries.mode must be review, automatic, or disabled")
    adapters = sessions.get("source_adapters", [])
    if not isinstance(adapters, list) or any(
        adapter not in {"hermes", "openclaw", "file"} for adapter in adapters
    ):
        raise ValueError("session_summaries.source_adapters contains an unsupported adapter")
    if not isinstance(sessions.get("auto_approve"), bool):
        raise ValueError("session_summaries.auto_approve must be boolean")
    if sessions.get("max_sensitivity") not in SENSITIVITY_RANK:
        raise ValueError("session_summaries.max_sensitivity is invalid")
    max_turns = sessions.get("max_turns")
    if not isinstance(max_turns, int) or not 2 <= max_turns <= 200:
        raise ValueError("session_summaries.max_turns must be between 2 and 200")
    for key in (
        "include_pending_tasks",
        "include_decisions",
        "include_emotional_context",
        "include_system_messages",
        "include_tool_messages",
    ):
        if not isinstance(sessions.get(key), bool):
            raise ValueError(f"session_summaries.{key} must be boolean")
    if sessions.get("include_system_messages") or sessions.get("include_tool_messages"):
        raise ValueError("system and tool messages cannot be synchronized in Phase 7")
    if sessions.get("raw_session_import") not in {"disabled", "preview-only"}:
        raise ValueError("session_summaries.raw_session_import must be disabled or preview-only")
    return value


def normalize_memory_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s@.+:/-]", "", text)
    return text


def memory_fingerprint(summary: str, memory_type: str = "note") -> str:
    normalized = normalize_memory_text(summary)
    return hashlib.sha256(f"{memory_type}\n{normalized}".encode("utf-8")).hexdigest()


def memory_key(
    summary: str,
    memory_type: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    metadata = metadata or {}
    explicit = metadata.get("memory_key") or metadata.get("key") or metadata.get("subject")
    if explicit:
        return normalize_memory_text(str(explicit))[:160]
    return memory_fingerprint(summary, memory_type)


_RESTRICTED_PATTERNS = (
    re.compile(r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)\b", re.I),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{12,})\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_PRIVATE_PATTERNS = (
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:\+?\d[\d ()-]{7,}\d)\b"),
    re.compile(r"\b(?:medical|diagnosis|medication|bank|account number|身份证|手机号|病历|药物|银行卡)\b", re.I),
)


def classify_sensitivity(summary: str, declared: str | None = None) -> str:
    declared_value = declared if declared in SENSITIVITY_RANK else "internal"
    detected = "internal"
    if any(pattern.search(summary) for pattern in _RESTRICTED_PATTERNS):
        detected = "restricted"
    elif any(pattern.search(summary) for pattern in _PRIVATE_PATTERNS):
        detected = "private"
    return max((declared_value, detected), key=lambda value: SENSITIVITY_RANK[value])
