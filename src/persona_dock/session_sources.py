from __future__ import annotations

import json
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from persona_dock.adapters.hermes import HermesAdapter, HermesAdapterError
from persona_dock.adapters.openclaw import OpenClawAdapter, OpenClawAdapterError
from persona_dock.sync_models import classify_sensitivity


_SECRET_PATTERNS = (
    re.compile(r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)\b\s*[:=]\s*\S+", re.I),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{12,})\b"),
)
_TASK_PATTERN = re.compile(
    r"\b(?:todo|to-do|need to|please|remember to|next step|follow up)\b|(?:待办|下一步|需要|请记得|跟进)",
    re.I,
)
_EMOTION_PATTERNS = {
    "anxious": re.compile(r"\b(?:anxious|worried|panic|nervous)\b|(?:焦虑|担心|紧张|害怕)", re.I),
    "sad": re.compile(r"\b(?:sad|upset|down|grief)\b|(?:难过|伤心|低落|失落)", re.I),
    "tired": re.compile(r"\b(?:tired|exhausted|burned out)\b|(?:疲惫|累|精疲力尽)", re.I),
    "positive": re.compile(r"\b(?:happy|excited|relieved|grateful)\b|(?:开心|兴奋|放松|感谢)", re.I),
}


@dataclass(frozen=True)
class SessionSummaryDraft:
    source_adapter: str
    source_session_id: str
    source_title: str
    started_at: str | None
    ended_at: str | None
    summary: str
    pending_tasks: tuple[str, ...] = ()
    emotional_context: dict[str, Any] = field(default_factory=dict)
    sensitivity: str = "internal"
    generated_by: str = "platform"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_adapter": self.source_adapter,
            "source_session_id": self.source_session_id,
            "source_title": self.source_title,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "summary": self.summary,
            "pending_tasks": list(self.pending_tasks),
            "emotional_context": self.emotional_context,
            "sensitivity": self.sensitivity,
            "generated_by": self.generated_by,
            "metadata": self.metadata,
        }


def _json_items(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _parse_json(text: str, label: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} returned invalid JSON: {error}") from error


def _value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def redact_text(value: str) -> str:
    text = value
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _message_role(item: dict[str, Any]) -> str:
    return str(_value(item, "role", "type", "speaker") or "").lower()


def _message_text(item: dict[str, Any]) -> str:
    value = _value(item, "content", "text", "message", "prompt")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for entry in value:
            if isinstance(entry, str):
                parts.append(entry)
            elif isinstance(entry, dict):
                text = _value(entry, "text", "content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def extract_safe_messages(payload: Any, *, max_messages: int, max_chars: int) -> list[dict[str, str]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("messages", "history", "transcript", "events"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = [item for item in value if isinstance(item, dict)]
                break
    elif isinstance(payload, list):
        candidates = [item for item in payload if isinstance(item, dict)]
    safe: list[dict[str, str]] = []
    used = 0
    for item in candidates:
        role = _message_role(item)
        if role not in {"user", "assistant"}:
            continue
        text = redact_text(_message_text(item))
        if not text:
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        text = text[:remaining]
        safe.append({"role": role, "content": text})
        used += len(text)
        if len(safe) >= max_messages:
            break
    return safe


def deterministic_summary(messages: Iterable[dict[str, str]]) -> tuple[str, tuple[str, ...], dict[str, Any]]:
    user_messages = [
        re.sub(r"\s+", " ", item.get("content", "")).strip()
        for item in messages
        if item.get("role") == "user" and item.get("content", "").strip()
    ]
    if not user_messages:
        return "", (), {}
    selected = user_messages[:2]
    if len(user_messages) > 2:
        selected.append(user_messages[-1])
    summary = "；".join(value[:320] for value in selected)
    tasks = tuple(value[:240] for value in user_messages if _TASK_PATTERN.search(value))[:8]
    emotional: dict[str, Any] = {}
    joined = "\n".join(user_messages)
    for label, pattern in _EMOTION_PATTERNS.items():
        if pattern.search(joined):
            emotional = {
                "label": label,
                "note": "Detected only from explicit user wording; review before sharing.",
            }
            break
    return summary, tasks, emotional


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            values.append(value)
    return values


class HermesSessionSource:
    def __init__(self, adapter: HermesAdapter, profile: str) -> None:
        self.adapter = adapter
        self.profile = profile

    def _arguments(self, *values: str) -> list[str]:
        return ["--profile", self.profile, *values]

    def list_sessions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        result = self.adapter.runner.run(
            self._arguments("sessions", "list", "--json"), timeout=60, check=True
        )
        payload = _parse_json(result.stdout, "Hermes sessions list")
        values = _json_items(payload, "sessions", "items", "data")
        return values[:limit]

    def _export_prompts(self, session_id: str) -> list[dict[str, str]]:
        if self.adapter.container:
            raise HermesAdapterError(
                "deterministic Hermes summary generation is local-only; container sessions require a platform summary or manual summary"
            )
        with tempfile.TemporaryDirectory(prefix="personadock-hermes-session-") as directory:
            output = Path(directory) / "session.jsonl"
            self.adapter.runner.run(
                self._arguments(
                    "sessions",
                    "export",
                    str(output),
                    "--format",
                    "jsonl",
                    "--session-id",
                    session_id,
                    "--only",
                    "user-prompts",
                    "--redact",
                ),
                timeout=180,
                check=True,
            )
            payloads = _read_jsonl(output)
            messages: list[dict[str, str]] = []
            for payload in payloads:
                messages.extend(
                    extract_safe_messages(payload, max_messages=100, max_chars=50000)
                )
            return messages

    def collect(self, *, limit: int = 20) -> list[SessionSummaryDraft]:
        drafts: list[SessionSummaryDraft] = []
        for raw in self.list_sessions(limit=limit):
            session_id = str(_value(raw, "id", "session_id", "sessionId") or "").strip()
            if not session_id:
                continue
            title = str(_value(raw, "title", "name") or session_id)
            platform_summary = str(_value(raw, "summary", "recap", "description") or "").strip()
            generated_by = "platform"
            tasks: tuple[str, ...] = ()
            emotional: dict[str, Any] = {}
            if not platform_summary:
                try:
                    messages = self._export_prompts(session_id)
                except HermesAdapterError:
                    continue
                platform_summary, tasks, emotional = deterministic_summary(messages)
                generated_by = "deterministic"
            if not platform_summary:
                continue
            drafts.append(
                SessionSummaryDraft(
                    source_adapter="hermes",
                    source_session_id=session_id,
                    source_title=title,
                    started_at=(
                        str(_value(raw, "started_at", "startedAt", "created_at", "createdAt"))
                        if _value(raw, "started_at", "startedAt", "created_at", "createdAt")
                        else None
                    ),
                    ended_at=(
                        str(_value(raw, "ended_at", "endedAt", "updated_at", "updatedAt"))
                        if _value(raw, "ended_at", "endedAt", "updated_at", "updatedAt")
                        else None
                    ),
                    summary=redact_text(platform_summary)[:4000],
                    pending_tasks=tasks,
                    emotional_context=emotional,
                    sensitivity=classify_sensitivity(platform_summary, "internal"),
                    generated_by=generated_by,
                    metadata={"profile": self.profile, "session": raw},
                )
            )
        return drafts

    def raw_preview(self, session_id: str, *, max_messages: int, max_chars: int) -> dict[str, Any]:
        if self.adapter.container:
            raise HermesAdapterError("experimental raw Hermes preview is local-only")
        with tempfile.TemporaryDirectory(prefix="personadock-hermes-preview-") as directory:
            output = Path(directory) / "session.jsonl"
            self.adapter.runner.run(
                self._arguments(
                    "sessions",
                    "export",
                    str(output),
                    "--format",
                    "jsonl",
                    "--session-id",
                    session_id,
                    "--redact",
                ),
                timeout=180,
                check=True,
            )
            payloads = _read_jsonl(output)
            messages: list[dict[str, str]] = []
            for payload in payloads:
                messages.extend(
                    extract_safe_messages(
                        payload,
                        max_messages=max_messages - len(messages),
                        max_chars=max_chars - sum(len(item["content"]) for item in messages),
                    )
                )
                if len(messages) >= max_messages:
                    break
            return {
                "adapter": "hermes",
                "profile": self.profile,
                "session_id": session_id,
                "messages": messages,
                "redacted": True,
                "excluded_roles": ["system", "tool", "tool_result", "reasoning"],
                "persisted": False,
            }


class OpenClawSessionSource:
    def __init__(self, adapter: OpenClawAdapter, agent_id: str) -> None:
        self.adapter = adapter
        self.agent_id = agent_id

    def list_transcripts(self, *, limit: int = 20) -> list[dict[str, Any]]:
        result = self.adapter.runner.run(
            ["transcripts", "list", "--json"], timeout=60, check=True
        )
        payload = _parse_json(result.stdout, "OpenClaw transcripts list")
        return _json_items(payload, "transcripts", "sessions", "items", "data")[:limit]

    def collect(self, *, limit: int = 20) -> list[SessionSummaryDraft]:
        drafts: list[SessionSummaryDraft] = []
        for raw in self.list_transcripts(limit=limit):
            selector = str(_value(raw, "selector", "sessionId", "session_id", "id") or "").strip()
            if not selector or raw.get("hasSummary") is False:
                continue
            show = self.adapter.runner.run(
                ["transcripts", "show", selector, "--json"], timeout=90
            )
            if not show.ok:
                continue
            payload = _parse_json(show.stdout, "OpenClaw transcripts show")
            if not isinstance(payload, dict):
                continue
            summary = str(
                _value(payload, "summary", "summaryMarkdown", "summary_markdown", "markdown")
                or ""
            ).strip()
            if not summary:
                continue
            title = str(_value(payload, "title") or _value(raw, "title") or selector)
            tasks_value = _value(payload, "pendingTasks", "pending_tasks")
            tasks = tuple(
                str(item).strip()
                for item in tasks_value
                if str(item).strip()
            ) if isinstance(tasks_value, list) else ()
            emotional = _value(payload, "emotionalContext", "emotional_context")
            emotional_context = dict(emotional) if isinstance(emotional, dict) else {}
            drafts.append(
                SessionSummaryDraft(
                    source_adapter="openclaw",
                    source_session_id=selector,
                    source_title=title,
                    started_at=(
                        str(_value(payload, "startedAt", "started_at") or _value(raw, "startedAt", "started_at"))
                        if _value(payload, "startedAt", "started_at") or _value(raw, "startedAt", "started_at")
                        else None
                    ),
                    ended_at=(
                        str(_value(payload, "stoppedAt", "endedAt", "ended_at") or _value(raw, "stoppedAt", "endedAt", "ended_at"))
                        if _value(payload, "stoppedAt", "endedAt", "ended_at") or _value(raw, "stoppedAt", "endedAt", "ended_at")
                        else None
                    ),
                    summary=redact_text(summary)[:4000],
                    pending_tasks=tasks,
                    emotional_context=emotional_context,
                    sensitivity=classify_sensitivity(summary, "internal"),
                    generated_by="platform",
                    metadata={"agent": self.agent_id, "selector": selector, "transcript": raw},
                )
            )
        return drafts

    def raw_preview(self, selector: str, *, max_messages: int, max_chars: int) -> dict[str, Any]:
        path_result = self.adapter.runner.run(
            ["transcripts", "path", selector, "--transcript", "--json"],
            timeout=90,
            check=True,
        )
        payload = _parse_json(path_result.stdout, "OpenClaw transcript path")
        if not isinstance(payload, dict):
            raise OpenClawAdapterError("OpenClaw transcript path response is not an object")
        path = str(_value(payload, "path", "transcriptPath", "transcript_path") or "").strip()
        if not path:
            raise OpenClawAdapterError("OpenClaw did not report a transcript export path")
        text = self.adapter.runner.read_text(path)
        if text is None:
            raise OpenClawAdapterError("OpenClaw transcript export could not be read")
        events: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
        messages = extract_safe_messages(events, max_messages=max_messages, max_chars=max_chars)
        return {
            "adapter": "openclaw",
            "agent": self.agent_id,
            "selector": selector,
            "messages": messages,
            "redacted": True,
            "excluded_roles": ["system", "tool", "tool_result", "reasoning"],
            "persisted": False,
            "materialized_export": path,
        }
