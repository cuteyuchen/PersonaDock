from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from persona_dock.registry import RegistryService
from persona_dock.session_models import (
    DEFAULT_SESSION_POLICY,
    SessionSummaryPolicyRecord,
    SessionSummaryRecord,
    deep_merge_policy,
    validate_session_policy,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _policy(row: sqlite3.Row) -> SessionSummaryPolicyRecord:
    return SessionSummaryPolicyRecord(
        id=str(row["id"]),
        persona_id=str(row["persona_id"]),
        config=json.loads(row["config_json"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _summary(row: sqlite3.Row) -> SessionSummaryRecord:
    return SessionSummaryRecord(
        id=str(row["id"]),
        persona_id=str(row["persona_id"]),
        fingerprint=str(row["fingerprint"]),
        source_adapter=str(row["source_adapter"]),
        source_runtime_instance_id=(
            str(row["source_runtime_instance_id"])
            if row["source_runtime_instance_id"]
            else None
        ),
        source_session_id=str(row["source_session_id"]),
        source_title=str(row["source_title"]),
        started_at=str(row["started_at"]) if row["started_at"] else None,
        ended_at=str(row["ended_at"]) if row["ended_at"] else None,
        summary=str(row["summary"]),
        pending_tasks=tuple(json.loads(row["pending_tasks_json"])),
        emotional_context=json.loads(row["emotional_context_json"]),
        sensitivity=str(row["sensitivity"]),
        sync_scope=str(row["sync_scope"]),
        status=str(row["status"]),
        generated_by=str(row["generated_by"]),
        metadata=json.loads(row["metadata_json"]),
        reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] else None,
        reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class SessionSummaryRegistry:
    def __init__(self, registry: RegistryService | None = None) -> None:
        self.registry = registry or RegistryService()
        self.registry.database.initialize()

    def get_policy(self, persona_id: str) -> SessionSummaryPolicyRecord:
        if self.registry.get_persona(persona_id) is None:
            raise ValueError(f"persona is not registered: {persona_id}")
        with self.registry.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM session_summary_policies WHERE persona_id = ?",
                (persona_id,),
            ).fetchone()
            if row is not None:
                return _policy(row)
            now = utc_now()
            policy_id = str(uuid.uuid4())
            config = validate_session_policy(DEFAULT_SESSION_POLICY)
            connection.execute(
                """
                INSERT INTO session_summary_policies(
                    id, persona_id, config_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    persona_id,
                    json.dumps(config, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM session_summary_policies WHERE id = ?",
                (policy_id,),
            ).fetchone()
            assert row is not None
            return _policy(row)

    def set_policy(
        self,
        persona_id: str,
        config: dict[str, Any],
        *,
        replace: bool = False,
    ) -> SessionSummaryPolicyRecord:
        current = self.get_policy(persona_id)
        resolved = validate_session_policy(
            config if replace else deep_merge_policy(current.config, config)
        )
        now = utc_now()
        with self.registry.database.session() as connection:
            connection.execute(
                "UPDATE session_summary_policies SET config_json = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(resolved, ensure_ascii=False, sort_keys=True),
                    now,
                    current.id,
                ),
            )
        self.registry.journal(
            "session-summary-policy-updated",
            persona_id=persona_id,
            payload={"policy_id": current.id, "config": resolved},
        )
        return self.get_policy(persona_id)

    def upsert_summary(
        self,
        *,
        persona_id: str,
        fingerprint: str,
        source_adapter: str,
        source_runtime_instance_id: str | None,
        source_session_id: str,
        source_title: str,
        started_at: str | None,
        ended_at: str | None,
        summary: str,
        pending_tasks: list[str] | tuple[str, ...],
        emotional_context: dict[str, Any],
        sensitivity: str,
        sync_scope: str,
        status: str,
        generated_by: str,
        metadata: dict[str, Any],
        reviewed_at: str | None = None,
        reviewed_by: str | None = None,
    ) -> tuple[SessionSummaryRecord, bool]:
        now = utc_now()
        summary_id = str(uuid.uuid4())
        with self.registry.database.session() as connection:
            existing = connection.execute(
                "SELECT * FROM session_summaries WHERE persona_id = ? AND fingerprint = ?",
                (persona_id, fingerprint),
            ).fetchone()
            if existing is not None:
                return _summary(existing), False
            connection.execute(
                """
                INSERT INTO session_summaries(
                    id, persona_id, fingerprint, source_adapter,
                    source_runtime_instance_id, source_session_id, source_title,
                    started_at, ended_at, summary, pending_tasks_json,
                    emotional_context_json, sensitivity, sync_scope, status,
                    generated_by, metadata_json, reviewed_at, reviewed_by,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary_id,
                    persona_id,
                    fingerprint,
                    source_adapter,
                    source_runtime_instance_id,
                    source_session_id,
                    source_title,
                    started_at,
                    ended_at,
                    summary,
                    json.dumps(list(pending_tasks), ensure_ascii=False),
                    json.dumps(emotional_context, ensure_ascii=False, sort_keys=True),
                    sensitivity,
                    sync_scope,
                    status,
                    generated_by,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    reviewed_at,
                    reviewed_by,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM session_summaries WHERE id = ?", (summary_id,)
            ).fetchone()
            assert row is not None
            return _summary(row), True

    def get_summary(self, summary_id: str) -> SessionSummaryRecord | None:
        with self.registry.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM session_summaries WHERE id = ?", (summary_id,)
            ).fetchone()
        return _summary(row) if row is not None else None

    def list_summaries(
        self,
        persona_id: str,
        *,
        status: str | None = None,
        source_adapter: str | None = None,
        sensitivity: str | None = None,
    ) -> list[SessionSummaryRecord]:
        clauses = ["persona_id = ?"]
        values: list[Any] = [persona_id]
        if status:
            clauses.append("status = ?")
            values.append(status)
        if source_adapter:
            clauses.append("source_adapter = ?")
            values.append(source_adapter)
        if sensitivity:
            clauses.append("sensitivity = ?")
            values.append(sensitivity)
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
        metadata_patch: dict[str, Any] | None = None,
    ) -> SessionSummaryRecord:
        current = self.get_summary(summary_id)
        if current is None:
            raise ValueError(f"session summary not found: {summary_id}")
        metadata = dict(current.metadata)
        if metadata_patch:
            metadata.update(metadata_patch)
        now = utc_now()
        reviewed_at = now if status in {"approved", "rejected", "superseded"} else current.reviewed_at
        with self.registry.database.session() as connection:
            connection.execute(
                """
                UPDATE session_summaries
                SET status = ?, sync_scope = ?, metadata_json = ?,
                    reviewed_at = ?, reviewed_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    sync_scope or current.sync_scope,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    reviewed_at,
                    reviewer or current.reviewed_by,
                    now,
                    summary_id,
                ),
            )
        value = self.get_summary(summary_id)
        assert value is not None
        return value

    def propagated(
        self,
        summary_id: str,
        destination_runtime_instance_id: str,
        content_hash: str,
    ) -> bool:
        with self.registry.database.session() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM session_summary_propagation
                WHERE session_summary_id = ?
                  AND destination_runtime_instance_id = ?
                  AND content_hash = ?
                  AND status = 'success'
                """,
                (summary_id, destination_runtime_instance_id, content_hash),
            ).fetchone()
        return row is not None

    def record_propagation(
        self,
        *,
        persona_id: str,
        session_summary_id: str,
        source_runtime_instance_id: str | None,
        destination_runtime_instance_id: str,
        content_hash: str,
        status: str,
        details: dict[str, Any],
    ) -> None:
        with self.registry.database.session() as connection:
            connection.execute(
                """
                INSERT INTO session_summary_propagation(
                    id, persona_id, session_summary_id,
                    source_runtime_instance_id, destination_runtime_instance_id,
                    content_hash, status, details_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_summary_id, destination_runtime_instance_id, content_hash)
                DO UPDATE SET status = excluded.status,
                              details_json = excluded.details_json,
                              created_at = excluded.created_at
                """,
                (
                    str(uuid.uuid4()),
                    persona_id,
                    session_summary_id,
                    source_runtime_instance_id,
                    destination_runtime_instance_id,
                    content_hash,
                    status,
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                    utc_now(),
                ),
            )

    def list_propagation(self, persona_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.registry.database.session() as connection:
            rows = connection.execute(
                """
                SELECT * FROM session_summary_propagation
                WHERE persona_id = ? ORDER BY created_at DESC LIMIT ?
                """,
                (persona_id, limit),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "persona_id": str(row["persona_id"]),
                "session_summary_id": str(row["session_summary_id"]),
                "source_runtime_instance_id": (
                    str(row["source_runtime_instance_id"])
                    if row["source_runtime_instance_id"]
                    else None
                ),
                "destination_runtime_instance_id": str(
                    row["destination_runtime_instance_id"]
                ),
                "content_hash": str(row["content_hash"]),
                "status": str(row["status"]),
                "details": json.loads(row["details_json"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def dashboard(self, persona_id: str) -> dict[str, Any]:
        policy = self.get_policy(persona_id)
        summaries = self.list_summaries(persona_id)
        counts = {status: 0 for status in ("pending", "approved", "rejected", "superseded")}
        for item in summaries:
            counts[item.status] = counts.get(item.status, 0) + 1
        return {
            "persona_id": persona_id,
            "policy": policy.to_dict(),
            "counts": counts,
            "summaries": [item.to_dict() for item in summaries],
            "propagation": self.list_propagation(persona_id),
        }
