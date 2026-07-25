from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from persona_dock.registry import RegistryService
from persona_dock.session_models import SessionSummaryDraft, SessionSummaryRecord
from persona_dock.sync_registry import _utc_now


def _summary(row: sqlite3.Row) -> SessionSummaryRecord:
    return SessionSummaryRecord(
        id=str(row["id"]),
        persona_id=str(row["persona_id"]),
        transcript_hash=str(row["transcript_hash"]),
        summary_hash=str(row["summary_hash"]),
        source_adapter=str(row["source_adapter"]),
        source_runtime_instance_id=(
            str(row["source_runtime_instance_id"])
            if row["source_runtime_instance_id"]
            else None
        ),
        source_session_id=str(row["source_session_id"]),
        source_title=str(row["source_title"]) if row["source_title"] else None,
        source_started_at=(str(row["source_started_at"]) if row["source_started_at"] else None),
        source_updated_at=(str(row["source_updated_at"]) if row["source_updated_at"] else None),
        summary=str(row["summary"]),
        pending_tasks=tuple(json.loads(row["pending_tasks_json"])),
        decisions=tuple(json.loads(row["decisions_json"])),
        emotional_context=tuple(json.loads(row["emotional_context_json"])),
        topics=tuple(json.loads(row["topics_json"])),
        sensitivity=str(row["sensitivity"]),
        sync_scope=str(row["sync_scope"]),
        status=str(row["status"]),
        message_count=int(row["message_count"]),
        user_message_count=int(row["user_message_count"]),
        assistant_message_count=int(row["assistant_message_count"]),
        metadata=json.loads(row["metadata_json"]),
        memory_item_id=str(row["memory_item_id"]) if row["memory_item_id"] else None,
        reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] else None,
        reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class SessionRegistry:
    def __init__(self, registry: RegistryService | None = None) -> None:
        self.registry = registry or RegistryService()
        self.registry.database.initialize()

    def upsert_summary(
        self,
        *,
        persona_id: str,
        source_adapter: str,
        source_runtime_instance_id: str | None,
        draft: SessionSummaryDraft,
        status: str = "pending",
        sync_scope: str = "local-only",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[SessionSummaryRecord, bool]:
        if self.registry.get_persona(persona_id) is None:
            raise ValueError(f"persona is not registered: {persona_id}")
        now = _utc_now()
        with self.registry.database.session() as connection:
            existing = connection.execute(
                """
                SELECT * FROM session_summaries
                WHERE persona_id = ?
                  AND source_runtime_instance_id IS ?
                  AND source_session_id = ?
                  AND transcript_hash = ?
                """,
                (
                    persona_id,
                    source_runtime_instance_id,
                    draft.source_session_id,
                    draft.transcript_hash,
                ),
            ).fetchone()
            if existing is not None:
                return _summary(existing), False
            summary_id = str(uuid.uuid4())
            merged_metadata = {**draft.metadata, **(metadata or {})}
            connection.execute(
                """
                INSERT INTO session_summaries(
                    id, persona_id, transcript_hash, summary_hash, source_adapter,
                    source_runtime_instance_id, source_session_id, source_title,
                    source_started_at, source_updated_at, summary, pending_tasks_json,
                    decisions_json, emotional_context_json, topics_json, sensitivity,
                    sync_scope, status, message_count, user_message_count,
                    assistant_message_count, metadata_json, memory_item_id,
                    reviewed_at, reviewed_by, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
                """,
                (
                    summary_id,
                    persona_id,
                    draft.transcript_hash,
                    draft.summary_hash,
                    source_adapter,
                    source_runtime_instance_id,
                    draft.source_session_id,
                    draft.source_title,
                    draft.source_started_at,
                    draft.source_updated_at,
                    draft.summary,
                    json.dumps(draft.pending_tasks, ensure_ascii=False),
                    json.dumps(draft.decisions, ensure_ascii=False),
                    json.dumps(draft.emotional_context, ensure_ascii=False),
                    json.dumps(draft.topics, ensure_ascii=False),
                    draft.sensitivity,
                    sync_scope,
                    status,
                    draft.message_count,
                    draft.user_message_count,
                    draft.assistant_message_count,
                    json.dumps(merged_metadata, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM session_summaries WHERE id = ?",
                (summary_id,),
            ).fetchone()
            assert row is not None
        self.registry.journal(
            "session-summary-created",
            persona_id=persona_id,
            runtime_instance_id=source_runtime_instance_id,
            payload={
                "summary_id": summary_id,
                "source_session_id": draft.source_session_id,
                "transcript_hash": draft.transcript_hash,
                "raw_persisted": False,
            },
        )
        return _summary(row), True

    def get(self, summary_id: str) -> SessionSummaryRecord | None:
        with self.registry.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM session_summaries WHERE id = ?",
                (summary_id,),
            ).fetchone()
        return _summary(row) if row is not None else None

    def list(
        self,
        persona_id: str,
        *,
        status: str | None = None,
        source_adapter: str | None = None,
    ) -> list[SessionSummaryRecord]:
        clauses = ["persona_id = ?"]
        values: list[Any] = [persona_id]
        if status:
            clauses.append("status = ?")
            values.append(status)
        if source_adapter:
            clauses.append("source_adapter = ?")
            values.append(source_adapter)
        query = (
            "SELECT * FROM session_summaries WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC, id"
        )
        with self.registry.database.session() as connection:
            rows = connection.execute(query, tuple(values)).fetchall()
        return [_summary(row) for row in rows]

    def update_status(
        self,
        summary_id: str,
        status: str,
        *,
        reviewer: str | None = None,
        sync_scope: str | None = None,
        memory_item_id: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> SessionSummaryRecord:
        current = self.get(summary_id)
        if current is None:
            raise ValueError(f"session summary not found: {summary_id}")
        metadata = dict(current.metadata)
        metadata.update(metadata_patch or {})
        now = _utc_now()
        reviewed_at = now if status in {"approved", "rejected", "superseded"} else current.reviewed_at
        with self.registry.database.session() as connection:
            connection.execute(
                """
                UPDATE session_summaries
                SET status = ?, sync_scope = ?, memory_item_id = ?, metadata_json = ?,
                    reviewed_at = ?, reviewed_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    sync_scope or current.sync_scope,
                    memory_item_id if memory_item_id is not None else current.memory_item_id,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    reviewed_at,
                    reviewer or current.reviewed_by,
                    now,
                    summary_id,
                ),
            )
        value = self.get(summary_id)
        assert value is not None
        self.registry.journal(
            f"session-summary-{status}",
            persona_id=value.persona_id,
            runtime_instance_id=value.source_runtime_instance_id,
            payload={"summary_id": summary_id, "sync_scope": value.sync_scope},
        )
        return value

    def record_import(
        self,
        *,
        persona_id: str,
        source_adapter: str,
        source_runtime_instance_id: str | None,
        source_session_id: str,
        transcript_hash: str,
        source_kind: str,
        source_reference: str | None,
        message_count: int,
        filtered_message_count: int,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        import_id = str(uuid.uuid4())
        with self.registry.database.session() as connection:
            existing = connection.execute(
                """
                SELECT id FROM session_imports
                WHERE persona_id = ? AND source_runtime_instance_id IS ?
                  AND source_session_id = ? AND transcript_hash = ?
                """,
                (
                    persona_id,
                    source_runtime_instance_id,
                    source_session_id,
                    transcript_hash,
                ),
            ).fetchone()
            if existing is not None:
                return str(existing["id"])
            connection.execute(
                """
                INSERT INTO session_imports(
                    id, persona_id, source_adapter, source_runtime_instance_id,
                    source_session_id, transcript_hash, source_kind,
                    source_reference, raw_persisted, message_count,
                    filtered_message_count, metadata_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    persona_id,
                    source_adapter,
                    source_runtime_instance_id,
                    source_session_id,
                    transcript_hash,
                    source_kind,
                    source_reference,
                    message_count,
                    filtered_message_count,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    _utc_now(),
                ),
            )
        return import_id

    def counts(self, persona_id: str) -> dict[str, int]:
        with self.registry.database.session() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM session_summaries WHERE persona_id = ? GROUP BY status",
                (persona_id,),
            ).fetchall()
        values = {"pending": 0, "approved": 0, "rejected": 0, "superseded": 0}
        values.update({str(row["status"]): int(row["count"]) for row in rows})
        return values
