from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

from persona_dock.sync_models import SENSITIVITY_RANK


SESSION_STATUSES = ("pending", "approved", "rejected", "superseded")
GENERATED_BY = ("platform", "deterministic", "manual")

DEFAULT_SESSION_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "mode": "review",
    "collect": {
        "enabled": True,
        "adapters": ["hermes", "openclaw"],
        "max_items_per_runtime": 20,
    },
    "auto_approve": {
        "enabled": False,
        "source_adapters": [],
        "generated_by": ["platform", "manual"],
        "max_sensitivity": "internal",
    },
    "propagation": {
        "enabled": True,
        "reviewed_only": True,
        "echo_to_source": False,
    },
    "raw_preview": {
        "enabled": False,
        "redact": True,
        "max_messages": 50,
        "max_chars": 20000,
    },
}


@dataclass(frozen=True)
class SessionSummaryPolicyRecord:
    id: str
    persona_id: str
    config: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionSummaryRecord:
    id: str
    persona_id: str
    fingerprint: str
    source_adapter: str
    source_runtime_instance_id: str | None
    source_session_id: str
    source_title: str
    started_at: str | None
    ended_at: str | None
    summary: str
    pending_tasks: tuple[str, ...]
    emotional_context: dict[str, Any]
    sensitivity: str
    sync_scope: str
    status: str
    generated_by: str
    metadata: dict[str, Any]
    reviewed_at: str | None
    reviewed_by: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["pending_tasks"] = list(self.pending_tasks)
        return value


@dataclass(frozen=True)
class SessionPropagationPlan:
    id: str
    persona_id: str
    policy: dict[str, Any]
    actions: tuple[dict[str, Any], ...]
    skipped: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "actions": list(self.actions),
            "skipped": list(self.skipped),
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


def validate_session_policy(config: dict[str, Any]) -> dict[str, Any]:
    value = deep_merge_policy(DEFAULT_SESSION_POLICY, config)
    if value.get("schema_version") != 1:
        raise ValueError("session summary policy schema_version must be 1")
    if value.get("mode") not in {"review", "automatic", "disabled"}:
        raise ValueError("session summary policy mode must be review, automatic, or disabled")
    collect = value.get("collect")
    if not isinstance(collect, dict) or not isinstance(collect.get("enabled"), bool):
        raise ValueError("session summary policy collect.enabled must be boolean")
    adapters = collect.get("adapters")
    if not isinstance(adapters, list) or any(
        adapter not in {"hermes", "openclaw"} for adapter in adapters
    ):
        raise ValueError("session summary policy collect.adapters contains an unsupported adapter")
    limit = collect.get("max_items_per_runtime")
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("collect.max_items_per_runtime must be between 1 and 100")
    auto = value.get("auto_approve")
    if not isinstance(auto, dict) or not isinstance(auto.get("enabled"), bool):
        raise ValueError("session summary policy auto_approve.enabled must be boolean")
    if auto.get("max_sensitivity") not in SENSITIVITY_RANK:
        raise ValueError("auto_approve.max_sensitivity is unsupported")
    generated = auto.get("generated_by")
    if not isinstance(generated, list) or any(item not in GENERATED_BY for item in generated):
        raise ValueError("auto_approve.generated_by contains an unsupported generator")
    source_adapters = auto.get("source_adapters")
    if not isinstance(source_adapters, list) or any(
        adapter not in {"hermes", "openclaw", "manual"} for adapter in source_adapters
    ):
        raise ValueError("auto_approve.source_adapters contains an unsupported adapter")
    propagation = value.get("propagation")
    if not isinstance(propagation, dict):
        raise ValueError("session summary policy propagation must be an object")
    for field in ("enabled", "reviewed_only", "echo_to_source"):
        if not isinstance(propagation.get(field), bool):
            raise ValueError(f"propagation.{field} must be boolean")
    raw = value.get("raw_preview")
    if not isinstance(raw, dict):
        raise ValueError("session summary policy raw_preview must be an object")
    for field in ("enabled", "redact"):
        if not isinstance(raw.get(field), bool):
            raise ValueError(f"raw_preview.{field} must be boolean")
    if not isinstance(raw.get("max_messages"), int) or not 1 <= raw["max_messages"] <= 200:
        raise ValueError("raw_preview.max_messages must be between 1 and 200")
    if not isinstance(raw.get("max_chars"), int) or not 1000 <= raw["max_chars"] <= 200000:
        raise ValueError("raw_preview.max_chars must be between 1000 and 200000")
    return value


def normalize_summary_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def session_summary_fingerprint(
    *,
    persona_id: str,
    source_adapter: str,
    source_session_id: str,
    summary: str,
) -> str:
    value = "\n".join(
        (
            persona_id,
            source_adapter,
            source_session_id,
            normalize_summary_text(summary),
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def session_summary_content_hash(record: SessionSummaryRecord) -> str:
    payload = json.dumps(
        {
            "summary": record.summary,
            "pending_tasks": list(record.pending_tasks),
            "emotional_context": record.emotional_context,
            "sync_scope": record.sync_scope,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_session_handoff(record: SessionSummaryRecord) -> str:
    lines = [f"Session: {record.source_title or record.source_session_id}", record.summary.strip()]
    if record.pending_tasks:
        lines.append("Pending tasks: " + "; ".join(record.pending_tasks))
    if record.emotional_context:
        label = str(record.emotional_context.get("label") or "").strip()
        note = str(record.emotional_context.get("note") or "").strip()
        if label or note:
            lines.append("Emotional context: " + " — ".join(value for value in (label, note) if value))
    return "\n".join(line for line in lines if line)
