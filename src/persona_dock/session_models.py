from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from persona_dock.sync_models import classify_sensitivity


SESSION_SUMMARY_STATUSES = ("pending", "approved", "rejected", "superseded")
_ALLOWED_ROLES = {"user", "assistant"}
_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{10,}\b"),
    re.compile(
        r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)\b\s*[:=]\s*([^\s,;]+)"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.S),
)
_DECISION_MARKERS = (
    "决定",
    "确定",
    "采用",
    "改为",
    "选择",
    "约定",
    "confirmed",
    "decided",
    "we will",
)
_TASK_MARKERS = (
    "下一步",
    "待办",
    "需要",
    "后续",
    "todo",
    "next step",
    "follow up",
)
_EMOTION_MARKERS = {
    "难过": "distressed",
    "焦虑": "anxious",
    "生气": "angry",
    "开心": "happy",
    "疲惫": "tired",
    "担心": "worried",
    "害怕": "afraid",
    "sad": "distressed",
    "anxious": "anxious",
    "angry": "angry",
    "happy": "happy",
    "tired": "tired",
    "worried": "worried",
    "afraid": "afraid",
}


@dataclass(frozen=True)
class SessionMessage:
    role: str
    content: str
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionDocument:
    session_id: str
    title: str | None
    source: str | None
    started_at: str | None
    updated_at: str | None
    messages: tuple[SessionMessage, ...]
    transcript_hash: str
    original_message_count: int
    filtered_message_count: int
    detected_sensitivity: str

    def to_dict(self, *, include_messages: bool = True) -> dict[str, Any]:
        value = asdict(self)
        if not include_messages:
            value.pop("messages", None)
        return value


@dataclass(frozen=True)
class SessionSummaryDraft:
    source_session_id: str
    source_title: str | None
    source_started_at: str | None
    source_updated_at: str | None
    transcript_hash: str
    summary_hash: str
    summary: str
    pending_tasks: tuple[str, ...]
    decisions: tuple[str, ...]
    emotional_context: tuple[str, ...]
    topics: tuple[str, ...]
    sensitivity: str
    message_count: int
    user_message_count: int
    assistant_message_count: int
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionSummaryRecord:
    id: str
    persona_id: str
    transcript_hash: str
    summary_hash: str
    source_adapter: str
    source_runtime_instance_id: str | None
    source_session_id: str
    source_title: str | None
    source_started_at: str | None
    source_updated_at: str | None
    summary: str
    pending_tasks: tuple[str, ...]
    decisions: tuple[str, ...]
    emotional_context: tuple[str, ...]
    topics: tuple[str, ...]
    sensitivity: str
    sync_scope: str
    status: str
    message_count: int
    user_message_count: int
    assistant_message_count: int
    metadata: dict[str, Any]
    memory_item_id: str | None
    reviewed_at: str | None
    reviewed_by: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def redact_sensitive_text(value: str) -> str:
    text = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED SECRET]", text)
    return text


def _text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                kind = str(item.get("type") or "").lower()
                if kind in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text") or item.get("content") or ""))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "content", "value"):
            if key in value:
                return _text_content(value[key])
    return ""


def _message_from(value: Any) -> tuple[str, str, str | None] | None:
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("message"), dict):
        value = value["message"]
    role = str(value.get("role") or value.get("author") or "").lower()
    if isinstance(value.get("author"), dict):
        role = str(value["author"].get("role") or value["author"].get("name") or role).lower()
    if role not in _ALLOWED_ROLES:
        return None
    content = _text_content(value.get("content") or value.get("text") or value.get("message"))
    content = redact_sensitive_text(content).strip()
    if not content:
        return None
    timestamp = value.get("timestamp") or value.get("created_at") or value.get("createdAt")
    return role, content[:12000], str(timestamp) if timestamp else None


def _session_candidates(objects: list[Any]) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    loose_messages: list[Any] = []
    for value in objects:
        if not isinstance(value, dict):
            continue
        if isinstance(value.get("sessions"), list):
            sessions.extend(item for item in value["sessions"] if isinstance(item, dict))
            continue
        if any(isinstance(value.get(key), list) for key in ("messages", "history", "transcript", "events")):
            sessions.append(value)
            continue
        if _message_from(value) is not None or isinstance(value.get("message"), dict):
            loose_messages.append(value)
    if loose_messages:
        sessions.append({"id": "imported-session", "messages": loose_messages})
    return sessions


def parse_session_export(
    path: str | Path,
    *,
    session_id: str | None = None,
) -> list[SessionDocument]:
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    raw = source_path.read_text(encoding="utf-8", errors="replace")
    objects: list[Any] = []
    try:
        parsed = json.loads(raw)
        objects = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for line_number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                objects.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid session JSONL at line {line_number}: {error}") from error

    documents: list[SessionDocument] = []
    for index, value in enumerate(_session_candidates(objects), 1):
        resolved_id = str(
            value.get("id")
            or value.get("session_id")
            or value.get("sessionId")
            or value.get("session_key")
            or value.get("sessionKey")
            or f"imported-session-{index}"
        )
        if session_id and resolved_id != session_id:
            continue
        raw_messages = next(
            (
                value[key]
                for key in ("messages", "history", "transcript", "events")
                if isinstance(value.get(key), list)
            ),
            [],
        )
        messages: list[SessionMessage] = []
        original_text: list[str] = []
        for raw_message in raw_messages:
            if isinstance(raw_message, dict):
                original_text.append(_text_content(raw_message.get("content") or raw_message.get("text") or raw_message.get("message")))
            parsed_message = _message_from(raw_message)
            if parsed_message is None:
                continue
            role, content, timestamp = parsed_message
            messages.append(SessionMessage(role=role, content=content, timestamp=timestamp))
        if not messages:
            continue
        canonical = "\n".join(f"{message.role}:{message.content}" for message in messages)
        transcript_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        detected = classify_sensitivity("\n".join(original_text))
        documents.append(
            SessionDocument(
                session_id=resolved_id,
                title=str(value.get("title") or value.get("label") or "") or None,
                source=str(value.get("source") or value.get("channel") or "") or None,
                started_at=str(value.get("started_at") or value.get("created_at") or value.get("createdAt") or "") or None,
                updated_at=str(value.get("updated_at") or value.get("ended_at") or value.get("updatedAt") or "") or None,
                messages=tuple(messages),
                transcript_hash=transcript_hash,
                original_message_count=len(raw_messages),
                filtered_message_count=len(raw_messages) - len(messages),
                detected_sensitivity=detected,
            )
        )
    if session_id and not documents:
        raise ValueError(f"session not found in export: {session_id}")
    return documents


def _sentences(messages: Iterable[SessionMessage], markers: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for message in messages:
        for sentence in re.split(r"(?<=[。！？.!?])\s+|\n+", message.content):
            clean = sentence.strip()
            lowered = clean.casefold()
            if clean and any(marker in lowered for marker in markers):
                clean = clean[:280]
                if clean not in values:
                    values.append(clean)
            if len(values) >= 8:
                return tuple(values)
    return tuple(values)


def build_session_summary(
    document: SessionDocument,
    *,
    max_turns: int = 20,
    include_emotional_context: bool = False,
) -> SessionSummaryDraft:
    if max_turns < 2:
        raise ValueError("max_turns must be at least 2")
    messages = list(document.messages[-max_turns:])
    users = [message for message in messages if message.role == "user"]
    assistants = [message for message in messages if message.role == "assistant"]
    first_user = users[0].content if users else ""
    last_user = users[-1].content if users else ""
    last_assistant = assistants[-1].content if assistants else ""
    title = document.title or (first_user[:80] if first_user else document.session_id)
    sections = [f"会话主题：{title}"]
    if first_user:
        sections.append(f"用户目标：{first_user[:420]}")
    if last_user and last_user != first_user:
        sections.append(f"最近请求：{last_user[:420]}")
    if last_assistant:
        sections.append(f"阶段结果：{last_assistant[:520]}")
    summary = "\n".join(sections)[:1800]
    decisions = _sentences(messages, _DECISION_MARKERS)
    pending_tasks = _sentences(messages, _TASK_MARKERS)
    emotional: list[str] = []
    if include_emotional_context:
        for message in users:
            lowered = message.content.casefold()
            for marker, label in _EMOTION_MARKERS.items():
                if marker in lowered and label not in emotional:
                    emotional.append(label)
    topics = tuple(value for value in (title[:100], document.source) if value)
    summary_hash = hashlib.sha256(
        json.dumps(
            {
                "summary": summary,
                "pending_tasks": pending_tasks,
                "decisions": decisions,
                "emotional_context": emotional,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return SessionSummaryDraft(
        source_session_id=document.session_id,
        source_title=document.title,
        source_started_at=document.started_at,
        source_updated_at=document.updated_at,
        transcript_hash=document.transcript_hash,
        summary_hash=summary_hash,
        summary=summary,
        pending_tasks=pending_tasks,
        decisions=decisions,
        emotional_context=tuple(emotional),
        topics=topics,
        sensitivity=document.detected_sensitivity,
        message_count=len(document.messages),
        user_message_count=len(users),
        assistant_message_count=len(assistants),
        metadata={
            "source": document.source,
            "original_message_count": document.original_message_count,
            "filtered_message_count": document.filtered_message_count,
            "raw_session_persisted": False,
            "system_messages_included": False,
            "tool_messages_included": False,
            "secret_redaction": True,
        },
    )
